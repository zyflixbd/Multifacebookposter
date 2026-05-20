"""
Facebook Multi-Page Auto Video Poster
- Each page gets UNIQUE videos — no video is repeated across pages
- Videos distributed round-robin: Page1→1,7,13... Page2→2,8,14... etc.
- 4 posts per page per day: 8AM, 12PM, 7PM, 10PM (IST/Kolkata)
- All pages share one Google Drive folder (1.mp4, 2.mp4, 3.mp4 ...)
- Each page tracks its own posted videos independently
"""

import os
import json
import random
import requests
import tempfile
from pathlib import Path

# ──────────────────────────────────────────────
# MULTI-PAGE CONFIG
# Secrets: PAGE_1_TOKEN, PAGE_1_ID ... PAGE_6_TOKEN, PAGE_6_ID
# ──────────────────────────────────────────────
def load_pages() -> list[dict]:
    pages = []
    for i in range(1, 7):
        token   = os.environ.get(f"PAGE_{i}_TOKEN", "").strip()
        page_id = os.environ.get(f"PAGE_{i}_ID",    "").strip()
        if token and page_id:
            pages.append({
                "index":   i - 1,        # 0-based index for round-robin
                "key":     f"page_{i}",
                "label":   f"Page {i}",
                "token":   token,
                "page_id": page_id,
            })
    return pages


# ──────────────────────────────────────────────
# GOOGLE DRIVE CONFIG
# ──────────────────────────────────────────────
DRIVE_FOLDER_ID = os.environ["GOOGLE_DRIVE_FOLDER_ID"]
GOOGLE_API_KEY  = os.environ["GOOGLE_API_KEY"]

DRIVE_API_BASE  = "https://www.googleapis.com/drive/v3"
FB_API_VERSION  = "v19.0"
FB_BASE         = f"https://graph.facebook.com/{FB_API_VERSION}"
POSTED_FILE     = "posted.json"

# ──────────────────────────────────────────────
# COMEDY CAPTIONS
# ──────────────────────────────────────────────
CAPTIONS = [
    "Best comedy scenes that will make your day 😂\n#Comedy #Viral",
    "When the timing is absolutely perfect 😂\n#Funny #ComedyShorts",
    "Viral comedy moments you can't miss 🤣\n#Viral #Comedy",
    "This one had us rolling on the floor 😂\n#Funny #Reels",
    "Comedy gold right here 🎬😂\n#ComedyMovies #Funny",
    "The funniest movie scenes ever caught on camera 🤣\n#Comedy #Viral",
    "POV: You needed a good laugh today 😂\n#Funny #ComedyShorts",
    "Legendary comedy moments 🎭😂\n#Comedy #Movies",
    "Warning: This will make you laugh out loud 🤣\n#Viral #Funny",
    "Comedy scenes that never get old 😂\n#ComedyMovies #Reels",
    "Best of Bollywood comedy — pure gold 😂\n#BollywoodComedy #Funny",
    "That one scene everyone knows by heart 🤣\n#Comedy #Viral",
    "When actors go full comedy mode 😂\n#Funny #Movies",
    "Iconic comedy moment — watch till the end 🎬😂\n#Comedy #Shorts",
    "This scene lives rent free in my head 🤣\n#Funny #ComedyShorts",
    "Absolute comedy perfection 😂\n#Viral #Comedy",
    "The classics never get old 🎭\n#ComedyMovies #Funny",
    "Guaranteed to make you smile 😄\n#Comedy #Reels",
    "When the whole cast is comedy legends 🤣\n#Funny #Viral",
    "Movie comedy scenes done right 🎬😂\n#Comedy #Shorts",
]


# ──────────────────────────────────────────────
# ROUND-ROBIN VIDEO ASSIGNMENT
#
# With N pages, videos are assigned like this:
#   Page 1 (index 0): videos 1, N+1, 2N+1, ...
#   Page 2 (index 1): videos 2, N+2, 2N+2, ...
#   Page 3 (index 2): videos 3, N+3, 2N+3, ...
#
# Example with 3 pages and videos 1..9:
#   Page1 → 1, 4, 7
#   Page2 → 2, 5, 8
#   Page3 → 3, 6, 9
#
# No page ever gets a video another page has already received.
# ──────────────────────────────────────────────
def get_assigned_videos(
    all_video_nums: list[int],
    page_index: int,
    total_pages: int
) -> list[int]:
    """Return the list of video numbers assigned to this page (round-robin)."""
    return [
        num for i, num in enumerate(all_video_nums)
        if i % total_pages == page_index
    ]


# ──────────────────────────────────────────────
# GOOGLE DRIVE helpers
# ──────────────────────────────────────────────

def list_drive_videos() -> dict[int, dict]:
    query = (
        f"'{DRIVE_FOLDER_ID}' in parents "
        f"and mimeType contains 'video/' "
        f"and trashed = false"
    )
    resp = requests.get(
        f"{DRIVE_API_BASE}/files",
        params={
            "q":        query,
            "fields":   "files(id, name)",
            "pageSize": 500,
            "key":      GOOGLE_API_KEY,
        },
        timeout=30,
    )
    resp.raise_for_status()

    video_map: dict[int, dict] = {}
    for f in resp.json().get("files", []):
        stem = Path(f["name"]).stem
        try:
            video_map[int(stem)] = f
        except ValueError:
            print(f"  [SKIP] '{f['name']}' — not a numbered filename.")

    return dict(sorted(video_map.items()))


def download_video(file_id: str, dest_path: str):
    url    = f"{DRIVE_API_BASE}/files/{file_id}"
    params = {"alt": "media", "key": GOOGLE_API_KEY}

    with requests.get(url, params=params, stream=True, timeout=600) as r:
        r.raise_for_status()
        total      = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(dest_path, "wb") as fh:
            for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                fh.write(chunk)
                downloaded += len(chunk)
                if total:
                    print(
                        f"    {downloaded / total * 100:.1f}%  "
                        f"({downloaded // (1024*1024)} MB)",
                        end="\r"
                    )
    print()


# ──────────────────────────────────────────────
# FACEBOOK helpers
# ──────────────────────────────────────────────

def upload_reel(video_path: str, description: str, token: str, page_id: str) -> str:
    file_size = os.path.getsize(video_path)
    print(f"    Size: {file_size / (1024*1024):.1f} MB")

    # Step 1 — Initialize
    print("    Step 1/3 — Initializing …")
    r = requests.post(
        f"{FB_BASE}/{page_id}/video_reels",
        data={"upload_phase": "start", "access_token": token},
        timeout=60,
    )
    r.raise_for_status()
    data       = r.json()
    video_id   = data["video_id"]
    upload_url = data["upload_url"]

    # Step 2 — Upload
    print("    Step 2/3 — Uploading …")
    with open(video_path, "rb") as vf:
        r = requests.post(
            upload_url,
            headers={
                "Authorization": f"OAuth {token}",
                "offset":        "0",
                "file_size":     str(file_size),
            },
            data=vf,
            timeout=600,
        )
    r.raise_for_status()

    # Step 3 — Publish
    print("    Step 3/3 — Publishing …")
    r = requests.post(
        f"{FB_BASE}/{page_id}/video_reels",
        data={
            "upload_phase": "finish",
            "video_id":     video_id,
            "access_token": token,
            "description":  description,
            "video_state":  "PUBLISHED",
        },
        timeout=120,
    )
    r.raise_for_status()
    print(f"    Result: {r.json()}")
    return video_id


# ──────────────────────────────────────────────
# TRACKING
# ──────────────────────────────────────────────

def load_posted() -> dict[str, list[int]]:
    if not Path(POSTED_FILE).exists():
        return {}
    with open(POSTED_FILE) as f:
        return json.load(f)


def save_posted(data: dict[str, list[int]]):
    with open(POSTED_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Facebook Multi-Page Auto Video Poster")
    print("=" * 60)

    pages = load_pages()
    if not pages:
        print("❌  No pages configured!")
        return

    total_pages = len(pages)
    print(f"\nActive pages: {total_pages}")
    for p in pages:
        print(f"  • {p['label']}  (ID: {p['page_id']})")

    # List all Drive videos
    print("\n[Drive] Fetching video list …")
    all_videos     = list_drive_videos()
    all_video_nums = sorted(all_videos.keys())
    if not all_video_nums:
        print("  No numbered videos found. Exiting.")
        return
    print(f"  Total videos in Drive: {len(all_video_nums)}")

    # Show assignment map
    print("\n[Assignment] Round-robin video distribution:")
    for page in pages:
        assigned = get_assigned_videos(all_video_nums, page["index"], total_pages)
        print(f"  {page['label']} → videos: {assigned[:8]}{'...' if len(assigned) > 8 else ''}")

    # Load tracking data
    posted_data = load_posted()

    # Find next video for each page
    to_post: dict[str, int] = {}   # page_key → video number
    for page in pages:
        key      = page["key"]
        assigned = get_assigned_videos(all_video_nums, page["index"], total_pages)
        posted   = set(posted_data.get(key, []))
        pending  = [n for n in assigned if n not in posted]
        if pending:
            to_post[key] = pending[0]
            print(f"\n  {page['label']}: next video → {all_videos[pending[0]]['name']}")
        else:
            print(f"\n  {page['label']}: ✅ all assigned videos posted!")

    if not to_post:
        print("\nNothing to post. All pages are up to date.")
        return

    # Download & post
    cache: dict[int, str] = {}   # num → local path (avoid re-downloading same file)

    with tempfile.TemporaryDirectory() as tmp:
        for page in pages:
            key = page["key"]
            if key not in to_post:
                continue

            num  = to_post[key]
            info = all_videos[num]

            print(f"\n{'─'*55}")
            print(f"[{page['label']}]  → {info['name']}")

            # Download only once per unique video number
            if num not in cache:
                local_path = os.path.join(tmp, info["name"])
                print(f"  Downloading from Drive …")
                download_video(info["id"], local_path)
                cache[num] = local_path
            else:
                print(f"  Using cached download.")

            caption = random.choice(CAPTIONS)
            print(f"  Caption: {caption[:60]}…")

            try:
                vid_id = upload_reel(
                    cache[num], caption,
                    page["token"], page["page_id"]
                )
                print(f"  ✅  Posted!  FB video_id = {vid_id}")

                # Update tracking
                if key not in posted_data:
                    posted_data[key] = []
                if num not in posted_data[key]:
                    posted_data[key].append(num)
                    posted_data[key].sort()
                save_posted(posted_data)

            except Exception as e:
                print(f"  ❌  Failed: {e}")

    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
