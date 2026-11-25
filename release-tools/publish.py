"""Promote a trusted successful main build into a versioned pre-release."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("join_iso", TOOLS / "join-iso.py")
join_iso = importlib.util.module_from_spec(spec)
spec.loader.exec_module(join_iso)
ISO, BUF = join_iso.ISO, join_iso.BUF
PART_BYTES = 1900 * 1024 * 1024


def check(condition, message):
    if not condition:
        raise SystemExit(message)


def split(source, dest, limit=PART_BYTES):
    expected, _ = join_iso.sha_line(
        (source / "SHA256SUMS").read_text().strip(), lambda name: name == ISO)
    full = hashlib.sha256()
    index, entries = 0, []
    with (source / ISO).open("rb") as inp:
        while first := inp.read(min(limit, BUF)):
            index += 1
            check(index <= 96, "Too many ISO parts")
            part = dest / f"{ISO}.part{index:03d}"
            h, remaining = hashlib.sha256(), limit
            with part.open("xb") as out:
                block = first
                while block:
                    out.write(block)
                    h.update(block)
                    full.update(block)
                    remaining -= len(block)
                    block = inp.read(min(BUF, remaining)) if remaining else b""
            entries.append(f"{h.hexdigest()}  {part.name}\n")
    check(index and full.hexdigest() == expected, "Source ISO SHA-256 mismatch")
    (dest / "PARTS.sha256").write_text("".join(entries))
    for filename in ("SHA256SUMS", "build-info.txt"):
        shutil.copyfile(source / filename, dest / filename)
    shutil.copyfile(TOOLS / "join-iso.py", dest / "join-iso.py")
    return index


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True).strip()


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    check(os.environ["GITHUB_REF"] == "refs/heads/main", "Only main can publish")
    if os.environ["GITHUB_EVENT_NAME"] == "push":
        config = json.loads((TOOLS.parent / "releases/bootstrap.json").read_text())
        run_id, sha = config["run_id"], config["expected_sha"]
    else:
        check(os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch", "Unexpected event")
        run_id, sha = os.environ["SOURCE_RUN_ID"], os.environ["SOURCE_COMMIT"]
    check(re.fullmatch(r"[1-9][0-9]{0,19}", run_id), "Invalid run ID")
    check(re.fullmatch(r"[0-9a-f]{40}", sha), "Provide a full commit SHA")
    base = f"repos/{repo}"
    run = json.loads(gh("api", f"{base}/actions/runs/{run_id}"))
    check(run["repository"]["full_name"] == repo
          and (run.get("head_repository") or {}).get("full_name") == repo
          and run["head_branch"] == "main"
          and run["head_sha"] == sha and run["conclusion"] == "success"
          and run["event"] in {"push", "workflow_dispatch"}
          and run["path"].split("@", 1)[0] == ".github/workflows/build-iso.yml",
          "Run is not the expected successful main ISO build")
    artifact = [x for x in json.loads(gh("api", f"{base}/actions/runs/{run_id}/artifacts",
                                        "--jq", ".artifacts"))
                if x["name"] == "bazzite-htpc-amd64" and not x["expired"]]
    check(len(artifact) == 1, "Expected one unexpired ISO artifact")
    tag = f"iso-run-{run_id}"
    with tempfile.TemporaryDirectory(prefix="bazzite-release-") as work:
        root = Path(work)
        check(shutil.disk_usage(root).free > 3 * artifact[0]["size_in_bytes"] + (1 << 30),
              "Not enough runner space to download and split the ISO")
        source, parts = root / "source", root / "parts"
        source.mkdir()
        parts.mkdir()
        gh("run", "download", run_id, "--repo", repo, "--name", "bazzite-htpc-amd64",
           "--dir", str(source))
        check(f"commit={sha}" in (source / "build-info.txt").read_text().splitlines(),
              "Artifact build-info does not identify the expected commit")
        count = split(source, parts)
        notes = root / "release-notes.md"
        notes.write_text(
            f"# 实验版 / Experimental ISO\n\n"
            f"Source: https://github.com/{repo}/actions/runs/{run_id} (commit `{sha}`).\n\n"
            f"下载全部 {count} 个 `.iso.partNNN`，以及 `SHA256SUMS`、`PARTS.sha256`、"
            f"`join-iso.py`，放进同一目录（Windows 建议 NTFS）。运行 "
            f"`py -3 join-iso.py`（Windows）或 `python3 join-iso.py`（Linux/macOS）。"
            f"脚本逐卷及整盘校验，成功后输出 `{ISO}`。需为分卷和合并后的 ISO 预留约 20 GB。\n\n"
            "尚未验证安装和首次启动。只在带空白虚拟磁盘的 UEFI 虚拟机里先断网试装，"
            "不要直接覆盖现有系统。This is not an official Bazzite release.\n",
            encoding="utf-8")
        releases = [json.loads(x) for x in gh("api", "--paginate", f"{base}/releases",
                    "--jq", f'.[] | select(.tag_name == "{tag}") | @json').splitlines()]
        check(len(releases) < 2, "Multiple releases for this tag")
        if not releases:
            refs = json.loads(gh("api", f"{base}/git/matching-refs/tags/{tag}"))
            check(not any(x["ref"] == f"refs/tags/{tag}" for x in refs),
                  "A tag already exists without the matching release")
            gh("release", "create", tag, "--repo", repo, "--target", sha, "--draft",
               "--prerelease", "--latest=false", "--title", f"Bazzite HTPC Live ISO (run {run_id})",
               "--notes-file", str(notes))
            releases = [json.loads(x) for x in gh("api", "--paginate", f"{base}/releases",
                        "--jq", f'.[] | select(.tag_name == "{tag}") | @json').splitlines()]
        check(len(releases) == 1 and releases[0]["target_commitish"] == sha
              and releases[0]["prerelease"], "Release does not match source build")
        release = releases[0]
        release_id = release["id"]

        def assets():
            return {a["name"]: a for a in json.loads(gh(
                "api", f"{base}/releases/{release_id}/assets?per_page=100"))}

        files = {p.name: p for p in parts.iterdir()}
        check(len(files) <= 100, "Too many assets for verification")
        expected = {}
        for filename, path in files.items():
            check(0 < path.stat().st_size < 2**31, f"Invalid asset size: {filename}")
            with path.open("rb") as f:
                expected[filename] = (path.stat().st_size, "sha256:" + hashlib.file_digest(f, "sha256").hexdigest())
        remote = assets()

        def matches(name, a):
            return (a["size"], a.get("digest")) == expected[name] and a["state"] == "uploaded"

        check(all(name in files and matches(name, a) for name, a in remote.items()),
              "Existing release contains unexpected or incomplete assets; no overwrite attempted")
        missing = sorted(set(files) - set(remote))
        if missing:
            check(release["draft"], "Published release is incomplete; not modifying it")
            for name in missing:
                print(f"Uploading {name}", flush=True)
                gh("release", "upload", tag, "--repo", repo, str(files[name]))
        remote = assets()
        check(set(remote) == set(files) and all(matches(n, a) for n, a in remote.items()),
              "Uploaded release sizes or digests do not match; leaving draft unpublished")
        if release["draft"]:
            refs = json.loads(gh("api", f"{base}/git/matching-refs/tags/{tag}"))
            check(all(x["object"]["sha"] == sha for x in refs if x["ref"] == f"refs/tags/{tag}"),
                  "Tag does not match source commit; leaving draft unpublished")
            gh("release", "edit", tag, "--repo", repo, "--draft=false", "--latest=false")
        published = json.loads(gh("api", f"{base}/releases/{release_id}"))
        ref = json.loads(gh("api", f"{base}/git/ref/tags/{tag}"))
        check(not published["draft"] and published["prerelease"] and ref["object"]["sha"] == sha,
              "Could not confirm published pre-release and matching source tag")
        print(published["html_url"])


if __name__ == "__main__":
    main()
