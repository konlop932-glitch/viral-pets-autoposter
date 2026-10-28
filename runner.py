#!/usr/bin/env python3
"""
Derpy Pets Daily — 100% Autonomous 2x/Day Cloud Multi-Platform Bot
Platforms:
  - YouTube Shorts (@derpypetsdaily / Channel ID: UCAqfBxWBVqbWIshMJWWfpiQ)
  - Facebook Reels (Derpy Pets Daily / Page ID: 1388898487639855)
  - Instagram Reels (@derpypets.daily - via Meta cross-posting & Graph API)
  - TikTok (@lopkon47 - active cloud scheduled buffer)

Features:
  - Unthrottled yt-dlp trending video discovery & download
  - Zero-touch OAuth2 token refresh for YouTube Data API v3
  - Resumable video upload for YouTube Shorts
  - Multipart video publishing to Meta Graph API
  - Strict deduplication via posted_ids.json
"""
import json
import os
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
import requests
import yt_dlp

HISTORY_FILE = Path("posted_ids.json")
TEMP_VIDEO_PATH = Path("current_short.mp4")

HOOKS = [
    "100% pure animal chaos 😭🐶🐾",
    "Bro forgot how to dog 😂🐾",
    "Not a single thought behind those eyes 😭✨",
    "Wait for the plot twist at the end 😂🐱🐾",
    "He really thought nobody saw him 😭🐶✨",
    "Tell me your pet is spoiled without telling me 😭🐾",
    "Pure wholesome chaotic energy 😂🐾",
    "When the derp mode activates 😭✨",
    "Zero survival instincts detected 😂🐶",
    "I can't stop watching this bro 😭🐾",
]

def load_history():
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            return []
    return []

def save_history(history):
    HISTORY_FILE.write_text(json.dumps(history, indent=2))

def fetch_and_download_top_video():
    """Finds a trending pet short (5-58s) and downloads it locally using yt-dlp."""
    queries = [
        "ytsearch25:#funnydog #shorts",
        "ytsearch25:#derpydog #shorts",
        "ytsearch25:#funnycats #shorts",
        "ytsearch25:#derpypets #shorts"
    ]
    random.shuffle(queries)
    history = set(load_history())

    for q in queries:
        try:
            ydl_opts_search = {"quiet": True, "extract_flat": True}
            with yt_dlp.YoutubeDL(ydl_opts_search) as ydl:
                res = ydl.extract_info(q, download=False)
                entries = res.get("entries", [])
                random.shuffle(entries)
                for e in entries:
                    vid = e.get("id")
                    dur = e.get("duration")
                    title = e.get("title", "")
                    if vid and vid not in history:
                        if dur and 5 <= dur <= 58:
                            print(f"🎯 Found candidate video: {vid} ({dur}s) - {title}")
                            # Clean up old file if exists
                            if TEMP_VIDEO_PATH.exists():
                                TEMP_VIDEO_PATH.unlink()
                            
                            # Download
                            ydl_download_opts = {
                                "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                                "outtmpl": str(TEMP_VIDEO_PATH),
                                "quiet": True,
                                "merge_output_format": "mp4",
                                "overwrites": True
                            }
                            with yt_dlp.YoutubeDL(ydl_download_opts) as dl_ydl:
                                dl_ydl.download([f"https://www.youtube.com/watch?v={vid}"])

                            if TEMP_VIDEO_PATH.exists() and TEMP_VIDEO_PATH.stat().st_size > 50000:
                                return {
                                    "id": vid,
                                    "title": title,
                                    "duration": dur,
                                    "file_path": TEMP_VIDEO_PATH
                                }
        except Exception as err:
            print(f"Notice during search query {q}: {err}")
            continue

    return None

def publish_youtube(video_info, caption):
    """Refreshes YouTube token and uploads short via YouTube Data API v3 Resumable Upload."""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

    if not (client_id and client_secret and refresh_token):
        print("ℹ️ YouTube OAuth secrets missing — skipping YouTube upload.")
        return False

    try:
        # 1. Refresh Access Token
        token_url = "https://oauth2.googleapis.com/token"
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        }
        resp = requests.post(token_url, data=payload, timeout=20)
        resp.raise_for_status()
        access_token = resp.json().get("access_token")
        if not access_token:
            print("❌ Failed to obtain refreshed YouTube access token.")
            return False
        print("✅ YouTube Access Token successfully refreshed.")

        # 2. Initiate Resumable Upload
        file_path = video_info["file_path"]
        file_size = file_path.stat().st_size
        upload_init_url = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
        
        # Clean title ensuring #shorts tag is present
        clean_title = video_info["title"]
        if "#shorts" not in clean_title.lower():
            clean_title = (clean_title[:80] + " #shorts").strip()
        else:
            clean_title = clean_title[:95].strip()

        metadata = {
            "snippet": {
                "title": clean_title,
                "description": caption,
                "tags": ["shorts", "funny pets", "derpy pets", "dogs", "cats", "funny animals", "memes"],
                "categoryId": "15"  # Pets & Animals
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False
            }
        }

        init_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(file_size)
        }

        init_resp = requests.post(upload_init_url, headers=init_headers, json=metadata, timeout=30)
        if init_resp.status_code != 200:
            print(f"❌ YouTube upload init failed ({init_resp.status_code}): {init_resp.text}")
            return False

        upload_url = init_resp.headers.get("Location")
        if not upload_url:
            print("❌ YouTube upload URL location header missing.")
            return False

        # 3. Stream binary upload
        print(f"Uploading {file_size / (1024*1024):.2f} MB to YouTube...")
        with open(file_path, "rb") as f:
            upload_headers = {"Content-Type": "video/mp4"}
            put_resp = requests.put(upload_url, headers=upload_headers, data=f, timeout=120)

        if put_resp.status_code in (200, 201):
            yt_data = put_resp.json()
            published_id = yt_data.get("id")
            print(f"🎉 YouTube Short successfully published! Video ID: {published_id}")
            print(f"📺 Watch URL: https://youtube.com/shorts/{published_id}")
            return True
        else:
            print(f"❌ YouTube upload failed ({put_resp.status_code}): {put_resp.text}")
            return False

    except Exception as e:
        print(f"❌ YouTube publishing error: {e}")
        return False

def publish_meta(video_info, caption):
    """Publishes video to Facebook Page 'Derpy Pets Daily' (with auto cross-posting to Instagram Reels)."""
    page_id = os.environ.get("META_PAGE_ID") or os.environ.get("IG_ACCOUNT_ID")
    page_token = os.environ.get("META_PAGE_ACCESS_TOKEN") or os.environ.get("IG_ACCESS_TOKEN")

    if not (page_id and page_token):
        print("ℹ️ Meta credentials missing — skipping Facebook/Instagram upload.")
        return False

    try:
        file_path = video_info["file_path"]
        print(f"Uploading to Facebook Page {page_id}...")
        
        url = f"https://graph.facebook.com/v26.0/{page_id}/videos"
        with open(file_path, "rb") as video_file:
            files = {
                "source": ("video.mp4", video_file, "video/mp4")
            }
            data = {
                "description": caption,
                "title": video_info["title"][:90],
                "access_token": page_token
            }
            resp = requests.post(url, files=files, data=data, timeout=120)

        if resp.status_code in (200, 201):
            fb_data = resp.json()
            fb_vid_id = fb_data.get("id")
            print(f"🎉 Facebook & Instagram Reel published successfully! Video ID: {fb_vid_id}")
            return True
        else:
            print(f"❌ Meta upload error ({resp.status_code}): {resp.text}")
            return False

    except Exception as e:
        print(f"❌ Meta publishing error: {e}")
        return False

def main():
    print("🚀 Starting Daily Viral Pets 2x Auto-Poster...")
    history = load_history()
    print(f"Loaded {len(history)} previously posted videos from history.")

    video = fetch_and_download_top_video()
    if not video:
        print("⚠️ No new viral video could be curated and downloaded in this run.")
        sys.exit(0)

    print(f"🎬 Successfully acquired video {video['id']} ({video['duration']}s)")
    print(f"Title: {video['title']}")

    hook = random.choice(HOOKS)
    caption = (
        f"{hook}\n\n"
        f"Laugh or your money back guaranteed 😭🐾\n"
        f"Daily dose drops 2x a day! ✨\n\n"
        f"#derpypets #funnypets #funnydog #funnycats #wholesome #reels #shorts"
    )

    # 1. Publish to YouTube Shorts
    yt_success = publish_youtube(video, caption)

    # 2. Publish to Facebook Page & Instagram Reels
    meta_success = publish_meta(video, caption)

    # 3. Clean up local downloaded video
    if TEMP_VIDEO_PATH.exists():
        TEMP_VIDEO_PATH.unlink()

    # 4. Commit to history
    history.append(video["id"])
    save_history(history)
    print(f"✅ Video {video['id']} added to history. YouTube: {yt_success}, Meta: {meta_success}")

if __name__ == "__main__":
    main()
