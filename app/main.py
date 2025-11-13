#!/usr/bin/env python3

from logger import info, ok, warning, error
from constants import SKILL_MAP

import os, sys, time, json, subprocess, hashlib
from collections import defaultdict
from datetime import datetime
import struct
import os

import io
import base64

import gspread
from google.oauth2.service_account import Credentials

from dotenv import load_dotenv



# .env support (cwd first, then folder of script)
def _load_env():
    # Try CWD .env, then script directory .env
    load_dotenv(dotenv_path=os.path.join(os.getcwd(), ".env"), override=False)
    base = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    load_dotenv(dotenv_path=os.path.join(base, ".env"), override=False)
_load_env()


def exe_dir():
    return os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))

# File parsing related configs
ROLE             = os.getenv("ROLE", "")
WORLD_NAME       = os.getenv("WORLD_NAME", "")
PLAYER_NAME      = os.getenv("PLAYER_NAME", "")
PLAYER_FILE_NAME = PLAYER_NAME + ".fch"
WORLD_SAVE_DIR   = os.getenv("WORLD_SAVE_DIR", "")
CHAR_SAVE_DIR    = os.getenv("CHAR_SAVE_DIR", "")

# General config
BASE_DIR = exe_dir()
INTERVAL_MINUTES = int(os.getenv("INTERVAL_MINUTES", "5"))
SHEET_NAME       = os.getenv("SHEET_NAME", "Valheim LAN Stats")

# Jar/creds default to files next to the exe unless overridden
JAR_PATH         = os.getenv("JAR_PATH") or os.path.join(BASE_DIR, "valheim-save-tools.jar")
GOOGLE_CREDS     = os.getenv("GOOGLE_CREDS") or os.path.join(BASE_DIR, "credentials.json")
JSON_OUT         = os.path.join(os.getenv("TEMP", BASE_DIR), "world.json")
WORLD_PATH       = os.path.join(WORLD_SAVE_DIR, WORLD_NAME)
PLAYER_PATH      = os.path.join(CHAR_SAVE_DIR, PLAYER_FILE_NAME.lower())

# ----- Player file parsing -----
def get_file_mtime(path: str) -> float:
    """Return last modification time of a file, or 0 if missing."""
    try:
        return os.path.getmtime(path)
    except FileNotFoundError:
        return 0

def find_skills_block(data: bytes):
    """Find the longest run of plausible (id, level, accum) triples."""
    best_start = None
    best_count = 0
    entry = 12

    for start in range(0, len(data) - entry):
        count = 0
        pos = start
        while pos + entry <= len(data) and count < 64:
            sid, lvl, acc = struct.unpack_from("<iff", data, pos)
            # id in a sane range, level non-crazy
            if 0 < sid < 200 and 0.0 <= lvl <= 1000.0:
                count += 1
                pos += entry
            else:
                break
        if count > best_count:
            best_count = count
            best_start = start

    return best_start, best_count


def decode_skills(path: str):
    with open(path, "rb") as f:
        data = f.read()

    start, count = find_skills_block(data)
    if start is None or count == 0:
        raise RuntimeError("Could not locate skills block")

    skills = {}
    entry = 12
    pos = start
    while pos + entry <= len(data):
        sid, lvl, acc = struct.unpack_from("<iff", data, pos)
        if not (0 < sid < 200 and 0.0 <= lvl <= 1000.0):
            break
        name = SKILL_MAP.get(sid, f"Skill_{sid}")
        skills[name] = round(lvl, 2)
        pos += entry

    return skills


# ----- Validation -----
def validate_config():
    missing = []
    if not ROLE: missing.append("ROLE")
    if not WORLD_NAME: missing.append("WORLD_NAME")
    if not PLAYER_NAME: missing.append("PLAYER_NAME")
    if not WORLD_SAVE_DIR:   missing.append("WORLD_SAVE_DIR")
    if not CHAR_SAVE_DIR: missing.append("CHAR_SAVE_DIR")

    if missing:
        raise SystemExit(f"Missing required .env keys: {', '.join(missing)}")
    if not os.path.exists(WORLD_SAVE_DIR):
        raise SystemExit(f"WORLD_SAVE_DIR does not exist: {WORLD_SAVE_DIR}")
    if not os.path.exists(WORLD_PATH):
        raise SystemExit(f"World file not found: {WORLD_PATH}")
    if not os.path.exists(JAR_PATH):
        raise SystemExit(f"valheim-save-tools.jar not found: {JAR_PATH}\n"
                         f"Place the jar next to the EXE or set JAR_PATH in .env.")
    if not os.path.exists(GOOGLE_CREDS):
        raise SystemExit(f"Google credentials JSON not found: {GOOGLE_CREDS}\n"
                         f"Place credentials.json next to the EXE or set GOOGLE_CREDS in .env.")

def require_java():
    try:
        result = subprocess.run(["java", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            raise RuntimeError()
        # Optional: check major version from stderr; many JREs print to stderr
    except Exception:
        raise SystemExit("Java not found. Install Java 17+ (Temurin/OpenJDK) and ensure 'java' is on PATH.")

# ----- Google Sheets -----
def sheets_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDS, scopes=scopes)
    return gspread.authorize(creds)

def get_or_create_sheet(gc, name):
    """Return a worksheet tab by name; create it if missing."""
    try:
        sh = gc.open(SHEET_NAME)
    except gspread.SpreadsheetNotFound:
        # Create the spreadsheet if it doesn't exist
        sh = gc.create(SHEET_NAME)
        ok(f"Created spreadsheet: {SHEET_NAME}")

    try:
        ws = sh.worksheet(name)
        info(f"Using existing sheet tab: {name}")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=1000, cols=20)
        ok(f"Created new tab: {name}")

    return ws

# ----- World export & parse -----
def export_world_json():
    cmd = f'java -jar "{JAR_PATH}" "{WORLD_PATH}" "{JSON_OUT}"'
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"valheim-save-tools failed:${result.stderr}")
    with open(JSON_OUT, "r", encoding="utf-8") as f:
        return f.read()

def read_u32(buf):
    return struct.unpack("<I", buf.read(4))[0]

def read_i32(buf):
    return struct.unpack("<i", buf.read(4))[0]

def read_f32(buf):
    return struct.unpack("<f", buf.read(4))[0]

def read_byte(buf):
    return struct.unpack("<B", buf.read(1))[0]

def read_u64(buf):
    return struct.unpack("<Q", buf.read(8))[0]

def decode_chest_items(zdo):
    items_b64 = zdo.get("stringsByName", {}).get("items")
    if not items_b64:
        return []

    raw = base64.b64decode(items_b64)
    buf = io.BytesIO(raw)

    _header = read_u32(buf)
    count = read_u32(buf)

    results = []

    for _ in range(count):
        # Basic item info
        name_len = read_byte(buf)
        name = buf.read(name_len).decode("utf-8", errors="replace")
        stack = read_i32(buf)
        durability = read_f32(buf)
        
        # Extended metadata
        equipped = read_byte(buf)  # 1 byte
        quality = read_i32(buf)    # 4 bytes
        variant = read_i32(buf)    # 4 bytes
        crafter_id = read_u64(buf) # 8 bytes
        
        has_crafter_name = read_byte(buf)  # 1 byte
        crafter_name = None
        if has_crafter_name:
            crafter_name_len = read_byte(buf)
            crafter_name = buf.read(crafter_name_len).decode("utf-8", errors="replace")
        
        remaining = 35 - (1 + 4 + 4 + 8 + 1)  # = 17 bytes
        if has_crafter_name and crafter_name:
            remaining -= (1 + len(crafter_name))
        buf.read(remaining)
        
        results.append({
            'name': name,
            'stack': stack,
            'durability': durability,
            'equipped': bool(equipped),
            'quality': quality,
            'variant': variant,
            'crafter_id': crafter_id,
            'crafter_name': crafter_name
        })

    return results

def aggregate_chests(world_json_obj):
    totals = defaultdict(int)
    all_items = []  # Store all items with their metadata

    zdos = world_json_obj.get("zdoList") or []

    for z in zdos:
        prefab = (z.get("prefabName") or "").lower()

        # detect chest
        if "piece_chest" in prefab:
            items_b64 = z.get("stringsByName", {}).get("items")
            if items_b64:
                items = decode_chest_items(z)
                for item_dict in items:
                    name = item_dict['name']
                    stack = item_dict['stack']
                    totals[name] += stack
                    all_items.append(item_dict)  # Keep full metadata
            else:
                print("Chest has no inventory")
    
    return totals  # Return both totals and detailed items

def upload_totals(sheet, totals):
    sheet.clear()
    sheet.append_row(["Item", "Total Count", "Last Updated (UTC)"])
    now = datetime.now().strftime('%H:%M:%S')
    # Batch write for speed
    rows = [[item, count, now] for item, count in sorted(totals.items(), key=lambda x: (-x[1], x[0]))]
    if rows:
        sheet.append_rows(rows, value_input_option="RAW")

def upload_skills(sheet, skills):
    """Upload player skill data to a Google Sheet tab."""
    sheet.clear()
    sheet.append_row(["Skill", "Level", "Last Updated (UTC)"])

    now = datetime.now().strftime('%H:%M:%S')
    rows = [[skill, level, now] for skill, level in sorted(skills.items())]

    if not rows:
        warning("No skills found to upload.")
        return

    try:
        sheet.append_rows(rows, value_input_option="RAW")
        ok(f"Uploaded {len(rows)} skills to {sheet.title}")
    except Exception as e:
        error(f"Failed to upload skills: {e}")


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def main_loop():
    info(f"Valheim Tracker — Role: {ROLE}, Player: {PLAYER_NAME}")
    info(f"World: {WORLD_PATH}")
    info(f"Sheet: {SHEET_NAME}")
    info(f"Interval: {INTERVAL_MINUTES} min")

    gc = sheets_client()
    last_hash = None
    last_m_time = 0

    while True:
        try:
            role = ROLE.lower()

            if role == "host":
                # Host uploads world/chest data
                require_java()
                validate_config()

                raw = export_world_json()
                h = sha256_str(raw)
                if h == last_hash:
                    info("No world change detected; skipping upload.")
                else:
                    data = json.loads(raw)
                    totals = aggregate_chests(data)
                    info(totals)
                    info(f"{len(totals)} item types found. Uploading…")
                    ws = get_or_create_sheet(gc, "World")
                    upload_totals(ws, totals)
                    ok(f"Updated World tab at {datetime.now().strftime('%H:%M:%S')}")
                    last_hash = h

            # Player uploads skill data
            if not os.path.exists(PLAYER_PATH):
                raise FileNotFoundError(f"Character file not found: {PLAYER_PATH}")

            ws_name = PLAYER_NAME
            ws = get_or_create_sheet(gc, ws_name)

            current_mtime  = get_file_mtime(PLAYER_PATH)
            if current_mtime != last_m_time:
                info(f"Detected new save for {PLAYER_NAME}, reading updated data...")
                last_m_time = current_mtime
                skills = decode_skills(PLAYER_PATH)
                if skills:
                    upload_skills(ws, skills)
                    ok(f"Updated {ws_name} tab at {datetime.now().strftime('%H:%M:%S')}")
                else:
                    warning("No skills parsed — player file might be incomplete or empty.")
            else:
                info(f"No new save yet, skipping upload. File mtime {current_mtime}")
        except Exception as e:
            error(str(e))

        time.sleep(INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    try:
        # Gentle hint if .env missing
        if not (os.path.exists(os.path.join(os.getcwd(), ".env")) or os.path.exists(os.path.join(BASE_DIR, ".env"))):
            error("Missing .env. Please copy .env.example to .env and configure it.")
            sys.exit(1)
        main_loop()
    except KeyboardInterrupt:
        warning("Exiting…")