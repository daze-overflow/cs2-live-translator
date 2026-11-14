globalThis.CS2PageContext = {
  read() {
    const heading = document.querySelector("h1.ytd-watch-metadata")?.textContent?.trim();
    const title = (heading || document.title.replace(/^\(\d+\)\s*/, "").replace(/ - YouTube$/, "")).replace(/\s+/g, " ");
    const chapter = (document.querySelector(".ytp-chapter-title-content")?.textContent || "").trim().replace(/\s+/g, " ");
    const video = document.querySelector("video");
    const url = new URL(location.href);
    return { title: [title, chapter].join(" | "), chapter,
      playing: Boolean(video && !video.paused && !video.seeking),
      videoId: url.searchParams.get("v") || url.pathname };
  }
};
