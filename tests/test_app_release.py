"""The app's release decisions (deploy/app_release.py, run by .github/workflows/mobile-release.yml).

Before this, a release was signed with the build machine's debug key, a new one on every CI run: the second release
could not be installed over the first. Now a release needs the owner's keystore from the repository secrets, and a
keystore other than the previous release's is refused before the build."""

import base64
import importlib.util
import io
import json
import shutil
import stat
import subprocess
import urllib.error
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("app_release", ROOT / "deploy" / "app_release.py")
app_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app_release)

CERT_A, CERT_B = "a" * 64, "b" * 64
PASSWORD, OTHER_PASSWORD = "made-for-this-test", "another-for-the-key"
needs_keytool = pytest.mark.skipif(shutil.which("keytool") is None, reason="keytool (a JDK) is not installed")


def _release(tag, build=None, cert=None, **more):
    body = "Joop AI for owners, staff and customers.\r\n\r\n"
    if build is not None:
        body += f"Version 1.0.0 (build {build})\r\n"
    if cert is not None:
        body += f"Signing certificate SHA-256: {cert}\r\n"
    return {"tag_name": tag, "body": body, "draft": False, "prerelease": False, **more}


class GitHub:
    """Answers the releases API with `found` (a list, or an exception to raise) and remembers what was asked."""

    def __init__(self, found):
        self.found, self.asked = found, []

    def __call__(self, request, timeout=None):
        self.asked.append((request.full_url, dict(request.header_items())))
        if isinstance(self.found, Exception):
            raise self.found
        return io.BytesIO(json.dumps(self.found).encode())


def _plan_env(**more):
    return {"VERSION": "mobile-v1.2.0", "RUN_NUMBER": "7", "HAS_KEYSTORE": "true", "HAS_PASSWORD": "true",
            "GITHUB_REPOSITORY": "Asilovvv/joop-ai", "GH_TOKEN": "t0ken", **more}


def _run(command, env, tmp_path, capsys, opener=None, argv=()):
    out = tmp_path / "github-output.txt"
    out.write_text("")
    code = app_release.main([command, *argv], {**env, "GITHUB_OUTPUT": str(out)}, opener or GitHub([]))
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines())
    return code, outputs, capsys.readouterr().out


def test_no_release_without_the_owners_key(tmp_path, capsys):
    github = GitHub([])
    code, outputs, said = _run("plan", _plan_env(HAS_KEYSTORE="false", HAS_PASSWORD="false"), tmp_path, capsys, github)
    assert code == 1 and outputs == {} and github.asked == []
    assert said.startswith("::error::") and "ANDROID_KEYSTORE_BASE64 and ANDROID_KEYSTORE_PASSWORD" in said
    assert "docs/deploy.md" in said and "no later version could be installed over it" in said
    code, _, said = _run("plan", _plan_env(HAS_PASSWORD=""), tmp_path, capsys)
    assert code == 1 and "add ANDROID_KEYSTORE_PASSWORD (" in said


def test_the_first_release_takes_its_version_from_the_tag(tmp_path, capsys):
    github = GitHub([])
    code, outputs, said = _run("plan", _plan_env(), tmp_path, capsys, github)
    assert code == 0 and outputs == {"name": "1.2.0", "build": "7", "previous_tag": "", "previous_cert": ""}
    assert "the first release" in said
    url, headers = github.asked[0]
    assert url == "https://api.github.com/repos/Asilovvv/joop-ai/releases?per_page=100&page=1"
    assert headers["Authorization"] == "Bearer t0ken" and "t0ken" not in said


@pytest.mark.parametrize("tag", ["", "v1.2.0", "mobile-v1.2", "mobile-v1.2.0-beta", "mobile-v1.2.0; rm -rf /", "1.2.0"])
def test_a_tag_that_is_not_a_version_is_refused(tag, tmp_path, capsys):
    code, outputs, said = _run("plan", _plan_env(VERSION=tag), tmp_path, capsys)
    assert code == 1 and outputs == {} and "must look like mobile-v1.0.0" in said


def test_the_build_number_rises_above_every_earlier_release(tmp_path, capsys):
    found = [_release("mobile-v1.1.0", 12, CERT_B), _release("mobile-v1.0.0", 3, CERT_A),
             _release("mobile-v0.9.0", 40, CERT_A, draft=True),  # a draft was never offered to anyone
             _release("server-v2.0.0", 90, CERT_A),  # not the app
             _release("mobile-v1.0.1", 50),  # no certificate line: not one of this workflow's releases
             {"tag_name": "mobile-v0.1.0", "body": None}]
    # the workflow's own counter started over (the file was renamed): still above the last release
    code, outputs, said = _run("plan", _plan_env(RUN_NUMBER="2"), tmp_path, capsys, GitHub(found))
    assert code == 0 and outputs == {"name": "1.2.0", "build": "13", "previous_tag": "mobile-v1.1.0", "previous_cert": CERT_B}
    assert "the previous release is mobile-v1.1.0" in said
    code, outputs, _ = _run("plan", _plan_env(RUN_NUMBER="30"), tmp_path, capsys, GitHub(found))
    assert outputs["build"] == "30"


def test_not_knowing_the_earlier_releases_stops_the_release(tmp_path, capsys):
    code, outputs, said = _run("plan", _plan_env(), tmp_path, capsys, GitHub(urllib.error.URLError("no network")))
    assert code == 1 and outputs == {} and "Could not read the earlier releases" in said
    code, _, said = _run("plan", _plan_env(), tmp_path, capsys, GitHub({"message": "rate limit"}))
    assert code == 1 and "run the workflow again" in said


def test_a_hundred_releases_a_page(tmp_path, capsys):
    class Paged(GitHub):
        def __call__(self, request, timeout=None):
            self.asked.append(request.full_url)
            page = int(request.full_url.rsplit("=", 1)[1])
            return io.BytesIO(json.dumps([_release(f"mobile-v1.0.{n}", n, CERT_A) for n in range(100)] if page == 1
                                         else [_release("mobile-v2.0.0", 500, CERT_B)]).encode())

    github = Paged([])
    code, outputs, _ = _run("plan", _plan_env(), tmp_path, capsys, github)
    assert code == 0 and len(github.asked) == 2 and outputs["build"] == "501" and outputs["previous_cert"] == CERT_B


# --- the keystore, with the JDK's real keytool ----------------------------------------------------------


@pytest.fixture(scope="module")
def keystores(tmp_path_factory):
    """Throwaway keystores made for these tests: `modern` as the guide makes it; `old` in the pre-Java-9 format
    with the key's own password; `other` a different key."""
    folder = tmp_path_factory.mktemp("keystores")

    def make(name, alias="joop", extra=()):
        path = folder / f"{name}.jks"
        subprocess.run(["keytool", "-genkeypair", "-keystore", str(path), "-storepass", PASSWORD, "-alias", alias,
                        "-keyalg", "RSA", "-keysize", "2048", "-validity", "30", "-dname", f"CN=Joop test {name}", *extra],
                       check=True, capture_output=True)
        listed = subprocess.run(["keytool", "-list", "-keystore", str(path), "-storepass", PASSWORD, "-J-Duser.language=en"],
                                check=True, capture_output=True, text=True).stdout
        cert = listed.split("(SHA-256): ", 1)[1].split()[0].replace(":", "").lower()
        return base64.b64encode(path.read_bytes()).decode(), cert

    return {"modern": make("modern"), "other": make("other"), "named": make("named", alias="release-key"),
            "old": make("old", extra=("-storetype", "JKS", "-keypass", OTHER_PASSWORD))}


def _key_env(keystores, tmp_path, which="modern", **more):
    return {"ANDROID_KEYSTORE_BASE64": keystores[which][0], "ANDROID_KEYSTORE_PASSWORD": PASSWORD,
            "ANDROID_KEYSTORE_PATH": str(tmp_path / "release.jks"), **more}


@needs_keytool
def test_the_keystore_from_the_secret_is_written_and_checked(keystores, tmp_path, capsys):
    wrapped = "\n".join(keystores["modern"][0][i:i + 76] for i in range(0, len(keystores["modern"][0]), 76)) + "\n"
    env = _key_env(keystores, tmp_path, ANDROID_KEYSTORE_BASE64=wrapped)  # pasted with line breaks, as `base64` prints it
    code, outputs, said = _run("keystore", env, tmp_path, capsys)
    assert code == 0 and outputs == {"cert": keystores["modern"][1]}
    assert said == f"Signing certificate SHA-256: {keystores['modern'][1]}\n"
    written = tmp_path / "release.jks"
    assert base64.b64encode(written.read_bytes()).decode() == keystores["modern"][0]
    assert stat.S_IMODE(written.stat().st_mode) == 0o600
    assert PASSWORD not in said and PASSWORD not in (tmp_path / "github-output.txt").read_text()


@needs_keytool
def test_a_wrong_password_is_found_before_the_build(keystores, tmp_path, capsys):
    code, outputs, said = _run("keystore", _key_env(keystores, tmp_path, ANDROID_KEYSTORE_PASSWORD="not-the-password"),
                               tmp_path, capsys)
    assert code == 1 and outputs == {}
    assert "ANDROID_KEYSTORE_PASSWORD does not open the keystore" in said and "not-the-password" not in said
    assert not (tmp_path / "release.jks").exists()  # a refused keystore does not stay on the machine


@needs_keytool
def test_the_keys_name_and_its_own_password(keystores, tmp_path, capsys):
    code, _, said = _run("keystore", _key_env(keystores, tmp_path, "named"), tmp_path, capsys)
    assert code == 1 and "no key named «joop» (it has: «release-key»)" in said and "ANDROID_KEY_ALIAS" in said
    code, outputs, _ = _run("keystore", _key_env(keystores, tmp_path, "named", ANDROID_KEY_ALIAS="release-key"), tmp_path, capsys)
    assert code == 0 and outputs == {"cert": keystores["named"][1]}
    code, _, said = _run("keystore", _key_env(keystores, tmp_path, "old"), tmp_path, capsys)
    assert code == 1 and "has a password of its own" in said and "ANDROID_KEY_PASSWORD" in said
    assert OTHER_PASSWORD not in said and PASSWORD not in said
    with_its_password = _key_env(keystores, tmp_path, "old", ANDROID_KEY_PASSWORD=OTHER_PASSWORD)
    code, outputs, _ = _run("keystore", with_its_password, tmp_path, capsys)
    assert code == 0 and outputs == {"cert": keystores["old"][1]}


@needs_keytool
@pytest.mark.parametrize("secret", ["", "not base64 at all!", base64.b64encode(b"a text file, not a keystore").decode()])
def test_a_secret_that_is_not_the_keystore(secret, keystores, tmp_path, capsys):
    code, outputs, said = _run("keystore", _key_env(keystores, tmp_path, ANDROID_KEYSTORE_BASE64=secret), tmp_path, capsys)
    assert code == 1 and outputs == {} and "ANDROID_KEYSTORE_BASE64 is not" in said and "docs/deploy.md" in said
    assert not (tmp_path / "release.jks").exists()


@needs_keytool
def test_another_key_than_the_previous_release_is_refused(keystores, tmp_path, capsys):
    previous = {"PREVIOUS_CERT": keystores["other"][1], "PREVIOUS_TAG": "mobile-v1.0.0"}
    code, outputs, said = _run("keystore", _key_env(keystores, tmp_path, **previous), tmp_path, capsys)
    assert code == 1 and outputs == {} and not (tmp_path / "release.jks").exists()
    assert "not the key release mobile-v1.0.0 was signed with" in said and "would refuse the update" in said
    # the owner says the key was replaced on purpose
    code, outputs, _ = _run("keystore", _key_env(keystores, tmp_path, NEW_KEY="true", **previous), tmp_path, capsys)
    assert code == 0 and outputs == {"cert": keystores["modern"][1]}
    # the same key as before: nothing to ask
    same = {"PREVIOUS_CERT": keystores["modern"][1].upper(), "PREVIOUS_TAG": "mobile-v1.0.0"}
    assert _run("keystore", _key_env(keystores, tmp_path, **same), tmp_path, capsys)[0] == 0


def test_without_java_the_reason_is_said(tmp_path, capsys):
    def no_keytool(*args, **kwargs):
        raise FileNotFoundError("keytool")

    out = tmp_path / "o.txt"
    env = {"ANDROID_KEYSTORE_BASE64": base64.b64encode(b"anything").decode(), "ANDROID_KEYSTORE_PASSWORD": PASSWORD,
           "ANDROID_KEYSTORE_PATH": str(tmp_path / "release.jks"), "GITHUB_OUTPUT": str(out)}
    assert app_release.main(["keystore"], env, run=no_keytool) == 1
    assert "keytool is not on this machine" in capsys.readouterr().out and not (tmp_path / "release.jks").exists()


# --- after the build ---------------------------------------------------------------------------------

APKSIGNER = """Signer #1 certificate DN: CN=Joop AI
Signer #1 certificate SHA-256 digest: {cert}
Signer #1 certificate SHA-1 digest: 7a8fa6d440803d81ddd651abf3a5a7454ef10566
Signer #1 certificate MD5 digest: 0f1e2d3c4b5a69788796a5b4c3d2e1f0
"""


def _signed(tmp_path, capsys, report, **more):
    (tmp_path / "certs.txt").write_text(report)
    env = {"EXPECTED_CERT": CERT_A, "BUILD_NAME": "1.2.0", "BUILD_NUMBER": "13", "API_URL": "https://joop.kg/",
           "GITHUB_SHA": "0123456789abcdef0123", "NOTES_PATH": str(tmp_path / "notes.md"), **more}
    return _run("signed", env, tmp_path, capsys, argv=(str(tmp_path / "certs.txt"),))


def test_the_notes_record_what_the_next_release_is_compared_with(tmp_path, capsys):
    code, _, said = _signed(tmp_path, capsys, APKSIGNER.format(cert=CERT_A.upper()), PREVIOUS_CERT=CERT_A)
    notes = (tmp_path / "notes.md").read_text()
    assert code == 0 and said == notes
    assert notes.splitlines() == [
        "Joop AI for owners, staff and customers. Server: https://joop.kg.", "",
        "Install the APK on Android and allow installing from this source when asked. It installs over an earlier "
        "version of the app.", "",
        "Version 1.2.0 (build 13)", f"Signing certificate SHA-256: {CERT_A}", "Commit: 0123456789ab"]
    # the round trip: the next release's plan reads this release back
    assert app_release.earlier([{"tag_name": "mobile-v1.2.0", "body": notes}]) == ("mobile-v1.2.0", CERT_A, 13)


def test_a_replaced_key_is_said_in_the_notes(tmp_path, capsys):
    code, _, said = _signed(tmp_path, capsys, APKSIGNER.format(cert=CERT_A), PREVIOUS_CERT=CERT_B)
    assert code == 0 and "signed with a new key: remove the earlier app from the phone first" in said
    assert "installs over an earlier version" not in said


@pytest.mark.parametrize("report, why", [
    (APKSIGNER.format(cert=CERT_B), "not signed with the key from the secrets"),  # the build fell back to another key
    (APKSIGNER.format(cert=CERT_A) + APKSIGNER.format(cert=CERT_B).replace("#1", "#2"), "not signed with the key"),
    ("DOES NOT VERIFY\n", "found no signing certificate"),
])
def test_an_apk_signed_with_anything_else_is_not_released(report, why, tmp_path, capsys):
    code, _, said = _signed(tmp_path, capsys, report)
    assert code == 1 and why in said and not (tmp_path / "notes.md").exists()


def test_usage(capsys):
    assert app_release.main([], {}) == 2 and app_release.main(["signed"], {}) == 2
    assert "usage: app_release.py plan | keystore | signed" in capsys.readouterr().out


# --- the workflows that call it -------------------------------------------------------------------------


def _workflow(name):
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def _steps(job):
    return [step for step in job["steps"] if "run" in step]


def test_the_release_workflow_never_builds_without_the_key():
    jobs = _workflow("mobile-release.yml")["jobs"]
    assert list(jobs) == ["check", "android", "publish"]
    assert any(step["run"].strip() == "python3 deploy/app_release.py plan" for step in _steps(jobs["check"]))
    runs = [step["run"] for step in _steps(jobs["android"])]
    key, build = next(i for i, run in enumerate(runs) if "app_release.py keystore" in run), \
        next(i for i, run in enumerate(runs) if "flutter build apk" in run)
    assert key < build < next(i for i, run in enumerate(runs) if "app_release.py signed" in run)
    step = _steps(jobs["android"])[build]
    assert "--build-name" in step["run"] and "--build-number" in step["run"]
    assert {"ANDROID_KEYSTORE_PATH", "ANDROID_KEYSTORE_PASSWORD"} <= set(step["env"])
    # secrets reach a step through its environment only, never pasted into a script; publishing has none of them
    for job in jobs.values():
        assert all("secrets." not in step["run"] and "inputs." not in step["run"] for step in _steps(job))
    assert "secrets." not in json.dumps(jobs["publish"])
    assert jobs["publish"]["permissions"] == {"contents": "write"}
    assert _workflow("mobile-release.yml")["permissions"] == {"contents": "read"}


def test_every_change_to_the_app_tries_the_signing_path():
    workflow = _workflow("mobile.yml")
    assert "deploy/app_release.py" in workflow[True]["pull_request"]["paths"]  # PyYAML reads the key `on` as True
    runs = "\n".join(step["run"] for step in _steps(workflow["jobs"]["android"]))
    assert "keytool -genkeypair" in runs and "app_release.py keystore" in runs and "app_release.py signed" in runs
