"""What the app's release workflow decides (.github/workflows/mobile-release.yml), kept where it can be tested.

A phone updates an installed Android app only when the new APK is signed with the same key and its build number
is higher. A release built without the owner's key is signed with the build machine's debug key, and every CI
machine makes a new one: such an APK installs once, and every later version is refused until the app is removed by
hand. So a release is signed with the owner's keystore from the repository secrets, and each release's notes record
its certificate and build number for the next release to be compared with:

  plan      before anything is built: the version name from the tag, a build number above every earlier release,
            and a refusal while the signing key is not in the secrets.
  keystore  writes the keystore from its secret to a file and checks the password, the key's name and that it is
            the key of the previous release, before a ten-minute build finds out.
  signed    after the build: the APK carries that key's certificate; writes the release notes.

Standard library and the JDK's keytool only: it runs on a bare GitHub runner. Settings come from the environment,
results go to $GITHUB_OUTPUT. It never prints a password or the keystore; a certificate's fingerprint is public
(anyone can read it from the APK).
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

TAG = re.compile(r"mobile-v(\d+\.\d+\.\d+)")
CERT_LINE = re.compile(r"^Signing certificate SHA-256: ([0-9a-f]{64})\s*$", re.M)
BUILD_LINE = re.compile(r"^Version \d+\.\d+\.\d+ \(build (\d+)\)\s*$", re.M)
APK_CERT = re.compile(r"certificate SHA-256 digest: ([0-9a-fA-F]{64})")
KEYSTORE_SHA256 = re.compile(r"^\s*SHA256: ([0-9A-Fa-f:]{95})\s*$", re.M)
KEYSTORE_ENTRY = re.compile(r"^(.+?), .+, (?:PrivateKeyEntry|trustedCertEntry|SecretKeyEntry),", re.M)
GUIDE = "docs/deploy.md, «The app's signing key»"
ALIAS = "joop"  # the name the guide gives the key; the Gradle build assumes the same (mobile/android/app/build.gradle.kts)
MAX_BUILD = 2_100_000_000  # Android's ceiling for a version code
TIMEOUT = 30


class Stop(Exception):
    """The release cannot go on; the message says what to do about it."""


def _yes(value) -> bool:
    return str(value or "").strip().lower() in ("true", "1", "yes")


def version_name(tag: str) -> str:
    """mobile-v1.2.0 -> 1.2.0, the version the phone shows."""
    found = TAG.fullmatch((tag or "").strip())
    if not found:
        raise Stop(f"The version must look like mobile-v1.0.0 (three numbers), not «{(tag or '').strip()[:60]}».")
    return found.group(1)


def releases(repo: str, token: str, opener=urllib.request.urlopen) -> list[dict]:
    """Every release of the repository, as GitHub's API gives them."""
    found: list[dict] = []
    for page in range(1, 11):
        request = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}",
            headers={"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})})
        try:
            with opener(request, timeout=TIMEOUT) as response:
                batch = json.loads(response.read() or b"[]")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # Not knowing the previous release's key is not a reason to guess: a wrong guess strands every phone.
            raise Stop(f"Could not read the earlier releases from GitHub ({type(exc).__name__}): "
                       "run the workflow again.") from None
        if not isinstance(batch, list):
            raise Stop("GitHub answered the list of releases with something else: run the workflow again.")
        found += [item for item in batch if isinstance(item, dict)]
        if len(batch) < 100:
            break
    return found


def earlier(found: list[dict]) -> tuple[str, str, int]:
    """(tag, certificate, build number) of the app release with the highest build number, from its notes;
    ("", "", 0) when there is none yet. Drafts were never offered to anyone; prereleases were."""
    best = ("", "", 0)
    for release in found:
        tag, body = str(release.get("tag_name") or ""), str(release.get("body") or "")
        if release.get("draft") or not TAG.fullmatch(tag):
            continue
        cert, build = CERT_LINE.search(body), BUILD_LINE.search(body)
        if cert and build and int(build.group(1)) > best[2]:
            best = (tag, cert.group(1), int(build.group(1)))
    return best


def plan(env, opener=urllib.request.urlopen) -> dict[str, str]:
    name = version_name(env.get("VERSION", ""))
    missing = [secret for secret, there in (("ANDROID_KEYSTORE_BASE64", env.get("HAS_KEYSTORE")),
                                            ("ANDROID_KEYSTORE_PASSWORD", env.get("HAS_PASSWORD"))) if not _yes(there)]
    if missing:
        raise Stop("The app's signing key is not in the repository secrets yet: add " + " and ".join(missing)
                   + f" ({GUIDE}: once, about 10 minutes). Without the owner's key a release would be signed with this "
                   "machine's one-off key, and no later version could be installed over it.")
    repo = env.get("GITHUB_REPOSITORY", "").strip()
    if not repo:
        raise Stop("GITHUB_REPOSITORY is not set: the workflow must say which repository's releases to read.")
    try:
        run = int(str(env.get("RUN_NUMBER") or "0").strip())
    except ValueError:
        run = 0
    tag, cert, build = earlier(releases(repo, env.get("GH_TOKEN", "").strip(), opener))
    number = max(run, build + 1, 1)  # above the last release even if the workflow's own counter started over
    if number > MAX_BUILD:
        raise Stop(f"The build number {number} is above Android's limit of {MAX_BUILD}.")
    return {"name": name, "build": str(number), "previous_tag": tag, "previous_cert": cert}


def _keytool(run, child: dict, *args: str) -> tuple[int, str]:
    try:
        done = run(["keytool", *args, "-J-Duser.language=en"], env=child, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise Stop("keytool is not on this machine (it comes with Java): the workflow must set Java up first.") from None
    except subprocess.TimeoutExpired:
        raise Stop("keytool did not answer in two minutes.") from None
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _first_error(report: str) -> str:
    return next((line.strip()[:200] for line in report.splitlines() if line.startswith("keytool error:")), "no reason given")


def keystore(env, run=subprocess.run) -> dict[str, str]:
    """Write the keystore to ANDROID_KEYSTORE_PATH and return its certificate; Stop when it would not sign this
    release or would sign it with another key than the previous one. A refused keystore does not stay on disk."""
    path = env.get("ANDROID_KEYSTORE_PATH", "").strip()
    if not path:
        raise Stop("ANDROID_KEYSTORE_PATH is not set: the workflow must say where the keystore goes.")
    try:
        data = base64.b64decode("".join(env.get("ANDROID_KEYSTORE_BASE64", "").split()), validate=True)
    except (binascii.Error, ValueError):
        data = b""
    if not data:
        raise Stop(f"The secret ANDROID_KEYSTORE_BASE64 is not the keystore file as base64 text ({GUIDE} has the "
                   "command that copies it).")
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as file:
        file.write(data)
    try:
        return _checked(env, run, path)
    except Stop:
        os.remove(path)
        raise


def _checked(env, run, path: str) -> dict[str, str]:
    alias = env.get("ANDROID_KEY_ALIAS", "").strip() or ALIAS
    store = env.get("ANDROID_KEYSTORE_PASSWORD", "")
    # Passwords reach keytool through its environment, never the command line, which other processes can read.
    child = {**os.environ, "JOOP_STORE_PASSWORD": store, "JOOP_KEY_PASSWORD": env.get("ANDROID_KEY_PASSWORD", "") or store}
    opened = ("-keystore", path, "-storepass:env", "JOOP_STORE_PASSWORD")
    code, report = _keytool(run, child, "-list", "-v", *opened, "-alias", alias)
    if code != 0:
        if "password was incorrect" in report:
            raise Stop("The password in the secret ANDROID_KEYSTORE_PASSWORD does not open the keystore.")
        if "does not exist" in report and "Alias" in report:
            _, listing = _keytool(run, child, "-list", *opened)
            names = ", ".join(f"«{name}»" for name in KEYSTORE_ENTRY.findall(listing)) or "none"
            raise Stop(f"The keystore has no key named «{alias}» (it has: {names}). Put the key's name into the secret "
                       "ANDROID_KEY_ALIAS.")
        raise Stop(f"The secret ANDROID_KEYSTORE_BASE64 is not a keystore Java can open ({_first_error(report)}). "
                   f"Copy the file again: {GUIDE}.")
    key_password = env.get("ANDROID_KEY_PASSWORD", "")
    if key_password and key_password != store and "Keystore type: PKCS12" in _keytool(run, child, "-list", *opened)[1]:
        # keytool ignores a key password for these (the guide's format, Java 9+), so the check below would pass and
        # the build fail ten minutes later: here the key's password is always the keystore's.
        raise Stop("This keystore has one password for the file and the key: delete the secret ANDROID_KEY_PASSWORD, "
                   "or set it to the same value as ANDROID_KEYSTORE_PASSWORD.")
    if "Entry type: PrivateKeyEntry" not in report:
        raise Stop(f"«{alias}» in the keystore is a certificate without its private key: an app cannot be signed with it.")
    found = KEYSTORE_SHA256.search(report)
    if not found:
        raise Stop("keytool did not print the certificate's SHA-256 fingerprint.")
    cert = found.group(1).replace(":", "").lower()
    # Signing needs the private key, which may have a password of its own (keystores made before Java 9).
    code, report = _keytool(run, child, "-certreq", "-alias", alias, *opened, "-keypass:env", "JOOP_KEY_PASSWORD")
    if code != 0:
        if "Cannot recover key" in report:
            raise Stop(f"The key «{alias}» has a password of its own, different from the keystore's: put it into the "
                       "secret ANDROID_KEY_PASSWORD.")
        raise Stop(f"The key «{alias}» cannot be used for signing ({_first_error(report)}).")
    previous, tag = env.get("PREVIOUS_CERT", "").strip().lower(), env.get("PREVIOUS_TAG", "").strip()
    if previous and previous != cert and not _yes(env.get("NEW_KEY")):
        raise Stop(f"This is not the key release {tag} was signed with: phones that have the app would refuse the update. "
                   "Put the first keystore back into the secrets. If it is lost for good, run again with «new_key» "
                   "ticked: everyone will then have to remove the app and install it again.")
    return {"cert": cert}


def notes(server: str, name: str, build: str, cert: str, commit: str, key_changed: bool) -> str:
    """The release's text. Its «Version» and «Signing certificate» lines are read back by `earlier`."""
    how = ("This version is signed with a new key: remove the earlier app from the phone first, then install this one."
           if key_changed else "It installs over an earlier version of the app.")
    lines = ["Joop AI for owners, staff and customers." + (f" Server: {server}." if server else ""), "",
             f"Install the APK on Android and allow installing from this source when asked. {how}", "",
             f"Version {name} (build {build})", f"Signing certificate SHA-256: {cert}"]
    if commit:
        lines.append(f"Commit: {commit}")
    return "\n".join(lines) + "\n"


def signed(env, report: str) -> str:
    """The release notes, once apksigner's report shows the APK signed with the expected certificate and no other."""
    expected = env.get("EXPECTED_CERT", "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise Stop("EXPECTED_CERT is not set: the workflow must pass the keystore's certificate.")
    found = {cert.lower() for cert in APK_CERT.findall(report)}
    if not found:
        raise Stop("apksigner found no signing certificate in the APK.")
    if found != {expected}:
        raise Stop("The APK is not signed with the key from the secrets (it carries " + ", ".join(sorted(found))
                   + "): the build did not use the keystore.")
    name, build = env.get("BUILD_NAME", "").strip(), env.get("BUILD_NUMBER", "").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", name) or not build.isdigit():
        raise Stop("BUILD_NAME and BUILD_NUMBER are not set: the workflow must pass the version it built.")
    previous = env.get("PREVIOUS_CERT", "").strip().lower()
    return notes(env.get("API_URL", "").strip().rstrip("/"), name, build, expected, env.get("GITHUB_SHA", "").strip()[:12],
                 bool(previous) and previous != expected)


def _output(env, values: dict[str, str]) -> None:
    path = env.get("GITHUB_OUTPUT", "")
    if path and values:
        with open(path, "a", encoding="utf-8") as file:
            file.writelines(f"{key}={value}\n" for key, value in values.items())


def main(argv=None, env=os.environ, opener=urllib.request.urlopen, run=subprocess.run) -> int:
    argv = sys.argv[1:] if argv is None else argv
    command = argv[0] if argv else ""
    try:
        if command == "plan":
            result = plan(env, opener)
            print(f"Version {result['name']}, build {result['build']}; "
                  + (f"the previous release is {result['previous_tag']}." if result["previous_tag"] else "the first release."))
        elif command == "keystore":
            result = keystore(env, run)
            print(f"Signing certificate SHA-256: {result['cert']}")
        elif command == "signed" and len(argv) == 2:
            with open(argv[1], encoding="utf-8", errors="replace") as file:
                text = signed(env, file.read())
            if env.get("NOTES_PATH"):
                with open(env["NOTES_PATH"], "w", encoding="utf-8") as file:
                    file.write(text)
            result = {}
            print(text, end="")
        else:
            print("usage: app_release.py plan | keystore | signed <apksigner's report>")
            return 2
    except Stop as stop:
        print("::error::" + str(stop).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A"))
        return 1
    _output(env, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
