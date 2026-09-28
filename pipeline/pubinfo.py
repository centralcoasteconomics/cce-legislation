"""Read the Legislative Counsel's nightly bulk file without downloading all of it.

The official source is https://downloads.leginfo.legislature.ca.gov/pubinfo_<year>.zip,
one archive per two-year session, rebuilt every night (about 1.3 GB). Roughly 95% of it is
bill text, analyses and code sections stored as .lob members; the relational tables we
need are ~50 MB. The server honours HTTP Range requests, so we read the zip's central
directory once (~20 MB for ~200k members), then fetch only the members we want, one range
request each, in parallel.

The .dat tables are MySQL-dump style: tab separated, strings wrapped in backticks, the
literal NULL for nulls, backslash escapes inside strings.
"""
from __future__ import annotations

import io
import re
import struct
import urllib.request
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor

BASE = "https://downloads.leginfo.legislature.ca.gov/"
UA = {"User-Agent": "cce-legislation/1.0 (+https://centralcoasteconomics.com/legislation)"}


def _open(url: str, headers: dict | None = None, timeout: int = 120):
    """urlopen with retries: the Legislature's server drops connections under load, and a
    dropped range read must never fail the whole nightly run."""
    import time
    last = None
    for wait in (0, 2, 6, 15, 30):
        if wait:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={**UA, **(headers or {})})
            return urllib.request.urlopen(req, timeout=timeout)
        except Exception as e:  # URLError, RemoteDisconnected, ConnectionResetError, timeouts
            last = e
    raise last


def head(url: str) -> dict:
    req = urllib.request.Request(url, method="HEAD", headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return {k.lower(): v for k, v in r.headers.items()}


class HttpRange(io.RawIOBase):
    """Seekable read-only file over HTTP Range requests (enough for zipfile's directory)."""

    def __init__(self, url: str, size: int):
        self.url, self.size, self.pos, self.fetched = url, size, 0, 0

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b""
        end = min(self.size, self.pos + n) - 1
        with _open(self.url, {"Range": f"bytes={self.pos}-{end}"}) as r:
            data = r.read()
        self.pos += len(data)
        self.fetched += len(data)
        return data

    def readinto(self, b):
        d = self.read(len(b))
        b[: len(d)] = d
        return len(d)


class Archive:
    """One session archive. `members` maps a bare file name (BILL_TBL.dat, *.lob) to its
    ZipInfo; `read(name)` fetches and inflates a single member with one range request."""

    def __init__(self, session_start_year: int, cache_dir=None):
        import json, os
        self.url = f"{BASE}pubinfo_{session_start_year}.zip"
        h = head(self.url)
        self.size = int(h["content-length"])
        self.last_modified = h.get("last-modified")
        self.etag = h.get("etag")
        dircache = os.path.join(cache_dir, "_directory.json") if cache_dir else None
        if dircache and os.path.exists(dircache):
            d = json.load(open(dircache))
            if d.get("etag") == self.etag:
                self.members = {}
                for n, (fn, off, csize, ctype) in d["m"].items():
                    zi = zipfile.ZipInfo(fn); zi.header_offset, zi.compress_size, zi.compress_type = off, csize, ctype
                    self.members[n] = zi
                self.directory_bytes = self.fetched = 0
                return
        raw = HttpRange(self.url, self.size)
        z = zipfile.ZipFile(io.BufferedReader(raw, buffer_size=4 << 20))
        self.members = {i.filename.rsplit("/", 1)[-1]: i for i in z.infolist()}
        self.directory_bytes = raw.fetched
        self.fetched = raw.fetched
        if dircache:
            json.dump({"etag": self.etag, "m": {n: [i.filename, i.header_offset, i.compress_size, i.compress_type]
                                                for n, i in self.members.items()}}, open(dircache, "w"))

    def read(self, name: str) -> bytes:
        zi = self.members[name]
        # local header is 30 bytes + name + extra; the extra length can differ from the
        # central directory's copy, so over-fetch a little and parse the real lengths.
        start = zi.header_offset
        end = start + 30 + len(zi.filename.encode()) + 1024 + zi.compress_size
        with _open(self.url, {"Range": f"bytes={start}-{min(end, self.size) - 1}"}) as r:
            buf = r.read()
        self.fetched += len(buf)
        sig, *_rest = struct.unpack("<I", buf[:4])
        if sig != 0x04034B50:
            raise ValueError(f"bad local header for {name}")
        nlen, xlen = struct.unpack("<HH", buf[26:30])
        data = buf[30 + nlen + xlen : 30 + nlen + xlen + zi.compress_size]
        if zi.compress_type == zipfile.ZIP_STORED:
            return data
        if zi.compress_type == zipfile.ZIP_DEFLATED:
            return zlib.decompress(data, -15)
        raise ValueError(f"unsupported compression {zi.compress_type} for {name}")

    def read_many(self, names: list[str], workers: int = 6) -> dict[str, bytes]:
        out: dict[str, bytes] = {}

        def one(n):
            for attempt in range(3):
                try:
                    return n, self.read(n)
                except Exception:
                    if attempt == 2:
                        raise
            return n, b""

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for n, b in ex.map(one, names):
                out[n] = b
        return out


# ---------------------------------------------------------------- .dat reader
_ESC = {"t": "\t", "n": "\n", "r": "\r", "\\": "\\", "`": "`", "0": "\0", "'": "'", '"': '"'}


def _val(v: str):
    if v == "NULL":
        return None
    if len(v) >= 2 and v[0] == "`" and v[-1] == "`":
        v = v[1:-1]
        if "\\" in v:
            v = re.sub(r"\\(.)", lambda m: _ESC.get(m.group(1), m.group(1)), v)
    return v


def rows(data: bytes, cols: list[str]):
    for line in data.decode("utf-8", "replace").splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < len(cols):
            continue
        yield dict(zip(cols, (_val(p) for p in parts[: len(cols)])))


def cols(s: str) -> list[str]:
    return s.split()


# Column orders from the Legislative Counsel's capublic schema (verified against the
# 2025-26 archive, 2026-09-28).
BILL = cols("bill_id session_year session_num measure_type measure_num measure_state chapter_year chapter_type chapter_session_num chapter_num latest_bill_version_id active_flg trans_uid trans_update current_location current_secondary_loc current_house current_status days_31st_in_print")
HIST = cols("bill_id bill_history_id action_date action trans_uid trans_update_dt action_sequence action_code action_status primary_location secondary_location ternary_location end_status")
VER = cols("bill_version_id bill_id version_num bill_version_action_date bill_version_action request_num subject vote_required appropriation fiscal_committee local_program substantive_changes urgency taxlevy bill_xml active_flg trans_uid trans_update")
AUTH = cols("bill_version_id type house name contribution committee_members active_flg trans_uid trans_update primary_author_flg")
VOTE = cols("bill_id location_code vote_date_time vote_date_seq motion_id ayes noes abstain vote_result trans_uid trans_update file_item_num file_location display_lines session_date")
MOTION = cols("motion_id motion_text trans_uid trans_update")
ANALYSIS = cols("analysis_id bill_id house analysis_type committee_code committee_name amendment_author analysis_date amendment_date page_num source_doc released_floor active_flg trans_uid trans_update")
VETO = cols("bill_id veto_date message trans_uid trans_update")
LOC = cols("session_year location_code location_type consent_calendar_code description long_description active_flg trans_uid trans_update inactive_file_flg")
LEGISLATOR = cols("district session_year legislator_name house author_name first_name last_name middle_initial name_suffix name_title web_name_title party active_flg trans_uid trans_update active_legislator")
HEARING = cols("bill_id committee_type committee_nr hearing_date location_code trans_uid trans_update")
AGENDA = cols("committee_code committee_desc agenda_date agenda_time line1 line2 line3 building_type room_num")
CODES = cols("code title")
