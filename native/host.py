"""Chrome's fixed-command, on-demand launcher. Stdout is only framed JSON."""
from contextlib import contextmanager
import ctypes as ct
from ctypes import wintypes as wt
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
_job_handle = None  # Non-inheritable; closing this host kills only its owned process tree.


def read_message(stream):
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise ValueError("Incomplete message header")
    size = struct.unpack('<I', header)[0]
    if not 0 < size <= 4096:
        raise ValueError("Invalid message length")
    body = stream.read(size)
    if len(body) != size:
        raise ValueError("Incomplete message")
    return json.loads(body.decode('utf-8'))


def write_message(stream, message):
    body = json.dumps(message, ensure_ascii=False).encode('utf-8')
    stream.write(struct.pack('<I', len(body)) + body)
    stream.flush()


def valid_request(message):
    return message == {"type": "start"}


def windows_api():
    api = ct.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateJobObjectW': (wt.HANDLE, [ct.c_void_p, wt.LPCWSTR]),
        'SetInformationJobObject': (wt.BOOL, [wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD]),
        'AssignProcessToJobObject': (wt.BOOL, [wt.HANDLE, wt.HANDLE]),
        'GetCurrentProcess': (wt.HANDLE, []),
        'CreateMutexW': (wt.HANDLE, [ct.c_void_p, wt.BOOL, wt.LPCWSTR]),
        'WaitForSingleObject': (wt.DWORD, [wt.HANDLE, wt.DWORD]),
        'ReleaseMutex': (wt.BOOL, [wt.HANDLE]),
        'CloseHandle': (wt.BOOL, [wt.HANDLE]),
    }
    for name, (result, arguments) in signatures.items():
        getattr(api, name).restype = result
        getattr(api, name).argtypes = arguments
    return api


def attach_job():
    class BasicLimits(ct.Structure):
        _fields_ = [('process_time', ct.c_int64), ('job_time', ct.c_int64), ('flags', wt.DWORD),
                    ('min_working_set', ct.c_size_t), ('max_working_set', ct.c_size_t),
                    ('active_processes', wt.DWORD), ('affinity', ct.c_size_t),
                    ('priority', wt.DWORD), ('scheduling', wt.DWORD)]

    class ExtendedLimits(ct.Structure):
        _fields_ = [('basic', BasicLimits), ('io_counters', ct.c_uint64 * 6),
                    ('process_memory', ct.c_size_t), ('job_memory', ct.c_size_t),
                    ('peak_process_memory', ct.c_size_t), ('peak_job_memory', ct.c_size_t)]

    api = windows_api()
    handle = api.CreateJobObjectW(None, None)
    limits = ExtendedLimits()
    limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not handle or not api.SetInformationJobObject(handle, 9, ct.byref(limits), ct.sizeof(limits)):
        error = ct.WinError(ct.get_last_error())
        if handle:
            api.CloseHandle(handle)
        raise error
    if not api.AssignProcessToJobObject(handle, api.GetCurrentProcess()):
        error = ct.WinError(ct.get_last_error())
        api.CloseHandle(handle)
        raise error
    return handle


@contextmanager
def startup_lock():
    api = windows_api()
    handle = api.CreateMutexW(None, False, 'Local\\CS2LiveTranslatorStartup')
    if not handle:
        raise ct.WinError(ct.get_last_error())
    try:
        if api.WaitForSingleObject(handle, 120000) not in (0, 0x80):
            raise RuntimeError('另一启动仍在准备中，请稍后重试。')
        try:
            yield
        finally:
            api.ReleaseMutex(handle)
    finally:
        api.CloseHandle(handle)


def health(port):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f'http://127.0.0.1:{port}/health', timeout=1) as response:
            data = json.load(response)
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None
    if data.get('app_id') != 'cs2-live-translator':
        raise RuntimeError('本机字幕端口被其他程序占用。')
    return data if data.get('ready') is True else None


def start_backend(root, send, timeout=120):
    global _job_handle
    port = json.loads((root / 'local-config.json').read_text(encoding='utf-8'))['port']
    ready = health(port)
    if ready:
        return {"type": "ready", "started": False, "version": ready['version']}
    send({"type": "progress", "message": "正在加载本机翻译模型，首次启动请稍候…"})
    with startup_lock():
        ready = health(port)
        if ready:
            return {"type": "ready", "started": False, "version": ready['version']}
        python = root / '.venv/Scripts/python.exe'
        if not python.is_file():
            raise RuntimeError('本机运行环境缺失，请运行一次 setup.ps1。')
        _job_handle = attach_job()
        (root / 'evidence').mkdir(exist_ok=True)
        with (root / 'evidence/startup.log').open('ab') as log:
            process = subprocess.Popen([str(python), '-X', 'utf8', '-m', 'backend.app'], cwd=root,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready = health(port)
            if ready:
                return {"type": "ready", "started": True, "version": ready['version'], "pid": process.pid}
            if process.poll() is not None:
                raise RuntimeError('本机模型启动失败，详情见 evidence/startup.log；可点击重试。')
            time.sleep(.2)
        raise RuntimeError('本机模型加载超时，请确认插电后重试。')


def main():
    import msvcrt
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    send = lambda message: write_message(sys.stdout.buffer, message)
    try:
        manifest = json.loads((ROOT / 'native/com.cs2.live_translator.json').read_text(encoding='utf-8'))
        origin = sys.argv[1].rstrip('/') + '/' if len(sys.argv) > 1 else ''
        if origin not in manifest['allowed_origins']:
            raise ValueError('Unexpected extension origin')
        request = read_message(sys.stdin.buffer)
        if not valid_request(request):
            raise ValueError('Only the fixed start request is supported')
        ready = start_backend(ROOT, send)
        send({**ready, "host_pid": os.getpid()})
        if read_message(sys.stdin.buffer) is not None:
            raise ValueError('A start connection accepts only one request')
    except Exception as error:
        send({"type": "error", "message": str(error)})
    # The OS closes _job_handle on exit, including on forced termination.


if __name__ == '__main__':
    main()
