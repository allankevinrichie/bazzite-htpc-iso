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
from urllib.parse import quote


TOOLS = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("join_iso", TOOLS / "join-iso.py")
join_iso = importlib.util.module_from_spec(spec)
spec.loader.exec_module(join_iso)
ISO = join_iso.ISO
ZIP = "bazzite-htpc-amd64.zip"
ZIP_LIMIT = "1900m"


def check(condition, message):
    if not condition:
        raise SystemExit(message)


def package_zip(source, dest, split_limit=ZIP_LIMIT):
    expected, _ = join_iso.sha_line(
        (source / "SHA256SUMS").read_text().strip(), lambda name: name == ISO)
    members = [ISO, "SHA256SUMS", "build-info.txt"]
    # Stable bytes across retries (including ZIP metadata).
    for name in members:
        os.utime(source / name, (946684800, 946684800))
    env = dict(os.environ, TZ="UTC")
    env.pop("ZIPOPT", None)
    archive = dest / ZIP
    subprocess.run(["zip", "-q", "-0", "-X", "-s", split_limit,
                    str(archive), *members], cwd=source, env=env, check=True)
    # Use an independent split-ZIP reader. Some Info-ZIP versions can
    # create spans but truncate an entry when converting back to one file.
    seven_zip = shutil.which("7zz") or shutil.which("7z")
    check(seven_zip, "A split-ZIP capable 7-Zip executable is required")
    listing = subprocess.check_output(
        [seven_zip, "l", "-slt", "--", str(archive)], env=env, text=True)
    reports = listing.split("----------", 1)
    check(len(reports) == 2, "Missing ZIP member listing")
    fields = reports[1].splitlines()
    check(sorted(line[7:] for line in fields if line.startswith("Path = ")) == sorted(members),
          "Unexpected ZIP members")
    check([line[9:] for line in fields if line.startswith("Method = ")] ==
          ["Store"] * len(members), "ZIP members must use Store")
    for name in members[1:]:
        data = subprocess.check_output([seven_zip, "x", "-so", "-bd", str(archive), name], env=env)
        check(data == (source / name).read_bytes(), f"Archive changes metadata: {name}")
    args = [seven_zip, "x", "-so", "-bd", str(archive), ISO]
    with subprocess.Popen(args, stdout=subprocess.PIPE, env=env) as p:
        digest = hashlib.file_digest(p.stdout, "sha256").hexdigest()
        check(p.wait() == 0 and digest == expected,
              "ISO in split ZIP does not match source SHA-256")
    volumes = {x.name for x in dest.iterdir()}
    count = len(volumes)
    prefix = ZIP.removesuffix(".zip")
    check(1 <= count <= 97 and volumes == (
        {ZIP} | {f"{prefix}.z{i:02d}" for i in range(1, count)}),
        "Unexpected split ZIP output")
    shutil.copyfile(source / "SHA256SUMS", dest / "SHA256SUMS")
    print(f"Verified {count} ZIP volume(s), Store mode, source ISO SHA-256 {expected}", flush=True)
    return count


def gh(*args):
    return subprocess.check_output(["gh", *args], text=True).strip()


def api_json(method, path, data):
    return json.loads(subprocess.check_output(
        ["gh", "api", "-X", method, path, "--input", "-"],
        input=json.dumps(data), text=True))


def upload(repo, release_id, path):
    # curl --upload-file streams rather than loading a 1900 MiB part into RAM.
    token = os.environ["GH_TOKEN"]
    check(re.fullmatch(r"[A-Za-z0-9_.-]+", token), "Unexpected GitHub token format")
    url = (f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets"
           f"?name={quote(path.name, safe='')}")
    return json.loads(subprocess.check_output(
        ["curl", "--silent", "--show-error", "--fail-with-body", "--request", "POST",
         "--header", "Content-Type: application/octet-stream", "--config", "-",
         "--upload-file", str(path), "--url", url],
        input=f'header = "Authorization: Bearer {token}"\n', text=True))


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
    check(len(artifact) <= 1, "More than one unexpired ISO artifact")
    source_marker = f"Source: https://github.com/{repo}/actions/runs/{run_id} (commit `{sha}`)."
    legacy_tag = f"iso-run-{run_id}"
    tag = legacy_tag + "-zip"
    legacy = None
    if not artifact:
        # Backfill the same build after the temporary artifact expires. Only
        # accept the previous verified, public same-repo promotion of this run.
        legacy = json.loads(gh("api", f"{base}/releases/tags/{legacy_tag}"))
        ref = json.loads(gh("api", f"{base}/git/ref/tags/{legacy_tag}"))
        check(not legacy["draft"] and legacy["prerelease"]
              and source_marker in (legacy.get("body") or "")
              and ref["object"]["type"] == "commit" and ref["object"]["sha"] == sha,
              "Legacy release does not match source build")
        parts_pattern = re.compile(re.escape(ISO) + r"\.part[0-9]{3}")
        data_size = sum(a["size"] for a in legacy["assets"] if parts_pattern.fullmatch(a["name"]))
        check(data_size > 0, "Legacy release has no ISO parts")
    else:
        data_size = artifact[0]["size_in_bytes"]
    with tempfile.TemporaryDirectory(prefix="bazzite-release-") as work:
        root = Path(work)
        check(shutil.disk_usage(root).free > 4 * data_size + (1 << 30),
              "Not enough runner space to download and split the ISO")
        source, parts = root / "source", root / "parts"
        source.mkdir()
        parts.mkdir()
        if legacy:
            gh("release", "download", legacy_tag, "--repo", repo, "--dir", str(source),
               "--pattern", ISO + ".part[0-9][0-9][0-9]",
               "--pattern", "SHA256SUMS", "--pattern", "PARTS.sha256",
               "--pattern", "build-info.txt")
            join_iso.join(source)
        else:
            gh("run", "download", run_id, "--repo", repo, "--name", "bazzite-htpc-amd64",
               "--dir", str(source))
        check(f"commit={sha}" in (source / "build-info.txt").read_text().splitlines(),
              "Artifact build-info does not identify the expected commit")
        count = package_zip(source, parts)
        notes = root / "release-notes.md"
        notes.write_text(
            f"# 实验版 / Experimental ISO\n\n"
            f"Source: https://github.com/{repo}/actions/runs/{run_id} (commit `{sha}`).\n\n"
            f"下载全部 {count} 个 ZIP 文件（最后一卷 `{ZIP}`，其余为 `.z01`、"
            "`.z02` 等），放在同一目录，不改名。用支持分卷 ZIP64 的解压工具（如 WinZip）打开"
            f"末卷 `{ZIP}`，解出 `{ISO}`。ZIP 仅归档，不压缩，不需要 Python。"
            "预留约 20 GB 空间，用归档内或单独附上的 `SHA256SUMS` 校验 ISO。\n\n"
            "尚未验证安装和首次启动。只在带空白虚拟磁盘的 UEFI 虚拟机里先断网试装，"
            "不要直接覆盖现有系统。This is not an official Bazzite release.\n",
            encoding="utf-8")
        title = f"Bazzite HTPC Live ISO (ZIP Store, run {run_id})"

        def tag_refs():
            return [x for x in json.loads(gh("api", f"{base}/git/matching-refs/tags/{tag}"))
                    if x["ref"] == f"refs/tags/{tag}"]

        pages = json.loads(gh("api", "--paginate", "--slurp", f"{base}/releases?per_page=100"))
        releases = [x for page in pages for x in page
                    if x["tag_name"] == tag or (x["draft"] and x["name"] == title)]
        check(len(releases) < 2, "Multiple releases or drafts match this run")
        if releases:
            release = releases[0]
        else:
            check(not tag_refs(), "A tag already exists without the matching release")
            release = api_json("POST", f"{base}/releases", {
                "tag_name": tag, "target_commitish": sha, "name": title,
                "body": notes.read_text(encoding="utf-8"), "draft": True,
                "prerelease": True, "make_latest": "false",
            })
        print(f"Matched release ID {release['id']}, tag={release['tag_name']!r}, "
              f"draft={release['draft']}, target={release['target_commitish']!r}", flush=True)
        check(release["name"] == title and source_marker in (release.get("body") or "")
              and (release["tag_name"] == tag or
                   release["draft"] and (not release["tag_name"] or
                                          release["tag_name"].startswith("untagged-"))),
              "Release does not match source build")
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
                uploaded = upload(repo, release_id, files[name])
                check(uploaded["name"] == name and matches(name, uploaded),
                      f"Upload metadata does not verify: {name}")
        remote = assets()
        check(set(remote) == set(files) and all(matches(n, a) for n, a in remote.items()),
              "Uploaded release sizes or digests do not match; leaving draft unpublished")
        refs = tag_refs()
        check(all(x["object"]["type"] == "commit" and x["object"]["sha"] == sha
                  for x in refs), "Tag does not match source commit")
        if release["draft"]:
            if not refs:
                api_json("POST", f"{base}/git/refs", {"ref": f"refs/tags/{tag}", "sha": sha})
            api_json("PATCH", f"{base}/releases/{release_id}", {
                "tag_name": tag, "draft": False, "prerelease": True, "make_latest": "false",
            })
        published = json.loads(gh("api", f"{base}/releases/{release_id}"))
        ref = json.loads(gh("api", f"{base}/git/ref/tags/{tag}"))
        check(not published["draft"] and published["prerelease"] and ref["object"]["sha"] == sha,
              "Could not confirm published pre-release and matching source tag")
        print(published["html_url"])


if __name__ == "__main__":
    main()
