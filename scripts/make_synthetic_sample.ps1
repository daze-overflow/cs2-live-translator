$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskOutput = Join-Path $taskRoot 'evidence/synthetic'
New-Item -ItemType Directory -Path $taskOutput -Force | Out-Null
$taskVoice = New-Object System.Speech.Synthesis.SpeechSynthesizer
$taskVoice.SelectVoice('Microsoft Zira Desktop')
$taskVoice.Rate = 2
Register-ObjectEvent -InputObject $taskVoice -EventName SpeakProgress -SourceIdentifier 'cs2-synthetic-words' | Out-Null
Register-ObjectEvent -InputObject $taskVoice -EventName PhonemeReached -SourceIdentifier 'cs2-synthetic-phonemes' | Out-Null
$taskFormat = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$taskPhrases = @(
    'Niko gets the opening kill.',
    'Navi are going back to the A bomb site.',
    'There is no time left to defuse the bomb.',
    'Falcons are trying to save their weapons.',
    'Monesy wins the one versus three.',
    'They have to go for the retake on Inferno.'
)
try {
    $taskReferences = @()
    for ($taskIndex = 0; $taskIndex -lt $taskPhrases.Count; $taskIndex++) {
        $taskVoice.SetOutputToWaveFile((Join-Path $taskOutput "$taskIndex.wav"), $taskFormat)
        $taskVoice.Speak($taskPhrases[$taskIndex])
        $taskWords = @(Get-Event -SourceIdentifier 'cs2-synthetic-words' | ForEach-Object { $_.SourceEventArgs })
        $taskPhones = @(Get-Event -SourceIdentifier 'cs2-synthetic-phonemes' | ForEach-Object { $_.SourceEventArgs })
        $taskTiming = @()
        for ($taskWordIndex = 0; $taskWordIndex -lt $taskWords.Count; $taskWordIndex++) {
            $taskWord = $taskWords[$taskWordIndex]
            $taskNext = if ($taskWordIndex + 1 -lt $taskWords.Count) { $taskWords[$taskWordIndex + 1].AudioPosition.TotalMilliseconds } else { [double]::PositiveInfinity }
            $taskEnd = ($taskPhones | Where-Object { $_.Phoneme -match '[^\p{C}\s]' -and $_.AudioPosition.TotalMilliseconds -ge $taskWord.AudioPosition.TotalMilliseconds -and $_.AudioPosition.TotalMilliseconds -lt $taskNext } | ForEach-Object { $_.AudioPosition.TotalMilliseconds + $_.Duration.TotalMilliseconds } | Measure-Object -Maximum).Maximum
            $taskTiming += [ordered]@{ word=$taskWord.Text; start_ms=$taskWord.AudioPosition.TotalMilliseconds; end_ms=$taskEnd }
        }
        $taskReferences += [ordered]@{ file="$taskIndex.wav"; sentence=$taskPhrases[$taskIndex]; words=$taskTiming }
        Get-Event -SourceIdentifier 'cs2-synthetic-words' | Remove-Event
        Get-Event -SourceIdentifier 'cs2-synthetic-phonemes' | Remove-Event
        $taskVoice.SetOutputToNull()
    }
    $taskPhrases | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskOutput 'phrases.json') -Encoding utf8
    $taskReferences | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $taskOutput 'reference-timings.json') -Encoding utf8
} finally {
    Unregister-Event -SourceIdentifier 'cs2-synthetic-words'
    Unregister-Event -SourceIdentifier 'cs2-synthetic-phonemes'
    $taskVoice.Dispose()
}
