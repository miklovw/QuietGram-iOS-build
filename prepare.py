"""Prepare a new QuietGram source checkout. Run with Python 3 and Git."""
from pathlib import Path
import subprocess

revision = "14a2ebfc4632055855d49926e31f2b0c6d6e8edc"
root = Path(__file__).resolve().parent / "source"
if root.exists():
    raise SystemExit(f"Destination already exists: {root}. Use a fresh directory.")
subprocess.run(["git", "init", str(root)], check=True)


def git(*args):
    subprocess.run(["git", "-C", str(root), *args], check=True)


git("remote", "add", "origin", "https://github.com/TelegramMessenger/Telegram-iOS.git")
git("fetch", "--depth=1", "origin", revision)
git("checkout", "-b", "quietgram", "FETCH_HEAD")
git("submodule", "update", "--init", "--recursive", "--jobs", "8")
path = root / "submodules/TelegramCore/Sources/State/ManagedLocalInputActivities.swift"
text = path.read_text(encoding="utf-8")
anchor = "private func requestActivity(postbox: Postbox, network: Network, accountPeerId: PeerId, peerId: PeerId, threadId: Int64?, activity: PeerInputActivity?) -> Signal<Void, NoError> {\n"
if text.count(anchor) != 1:
    raise SystemExit("Unexpected source version; patch not applied.")
path.write_text(text.replace(anchor, anchor + """    switch activity {
    case .typingText?, .recordingVoice?, .recordingInstantVideo?, .choosingSticker?:
        return .complete()
    default:
        break
    }
"""), encoding="utf-8")
# SDK 26.5 does not declare UIView.reservedRegions. Use the upstream
# no-division fallback when building this revision with Xcode 26.6.
window = root / "submodules/Display/Source/WindowContent.swift"
text = window.read_text(encoding="utf-8")
division = r"""        if #available(iOS 27.1, *) {
            return self.eventView.reservedRegions(kind: .division).first(where: \.isActive)?.frame
        }
"""
if text.count(division) != 1:
    raise SystemExit("Unexpected WindowContent.swift; SDK compatibility patch not applied.")
window.write_text(text.replace(division, ""), encoding="utf-8")
# Extensions are disabled in the sideload build. If the signed client has
# no shared container, use its own persistent sandbox for the main app.
delegate = root / "submodules/TelegramUI/Sources/AppDelegate.swift"
text = delegate.read_text(encoding="utf-8")
lookup = "let maybeAppGroupUrl = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroupName)"
background = "configuration.sharedContainerIdentifier = appGroupName"
if text.count(lookup) != 1 or text.count(background) != 1:
    raise SystemExit("Unexpected AppDelegate.swift; sideload storage patch not applied.")
text = text.replace(lookup, lookup + """
            ?? (try? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true))""")
text = text.replace(background, """if FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroupName) != nil {
            configuration.sharedContainerIdentifier = appGroupName
        }""")
delegate.write_text(text, encoding="utf-8")
def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"Unexpected pinned source; could not apply edit at {old!r}")
    return text.replace(old, new)


presence = root / "submodules/TelegramCore/Sources/State/ManagedAccountPresence.swift"
text = presence.read_text(encoding="utf-8")
anchor = "private final class AccountPresenceManagerImpl"
text = once(text, anchor, """public enum QuietGramPresenceSettings {
    private static let key = "QuietGram.hideOnline"
    public static var hidden: Bool {
        return UserDefaults.standard.object(forKey: key) as? Bool ?? true
    }
    private static let promise = ValuePromise<Bool>(hidden, ignoreRepeated: true)
    public static var changes: Signal<Bool, NoError> { return promise.get() }
    public static func setHidden(_ value: Bool) {
        UserDefaults.standard.set(value, forKey: key)
        promise.set(value)
    }
}

""" + anchor)
text = once(text, "(shouldKeepOnlinePresence\n        |> distinctUntilChanged",
            "(combineLatest(shouldKeepOnlinePresence, QuietGramPresenceSettings.changes)\n"
            "        |> map { foreground, hidden in foreground && !hidden }\n        |> distinctUntilChanged")
presence.write_text(text, encoding="utf-8")

settings = root / "submodules/SettingsUI/Sources/Privacy and Security/PrivacyAndSecurityController.swift"
text = settings.read_text(encoding="utf-8")
for anchor, before in [
    ("    case linkHandling\n", ""),
    ("    case openLinksIn(PresentationTheme, String, String)", "    case quietOnline(Bool)\n"),
    ("        case .openLinksIn:\n            return PrivacyAndSecuritySection", "        case .quietOnline:\n            return PrivacyAndSecuritySection.quietGram.rawValue\n"),
    ("            case .openLinksIn:\n                return 33", "            case .quietOnline:\n                return 34\n"),
    ("            case let .openLinksIn(lhsTheme", "            case let .quietOnline(value):\n                if case let .quietOnline(other) = rhs { return value == other }\n                return false\n"),
    ("            case let .openLinksIn(_, text, value):", """            case let .quietOnline(value):
                return ItemListSwitchItem(presentationData: presentationData, systemStyle: .glass, title: "Скрывать «в сети»", value: value, sectionId: self.section, style: .blocks, updated: { enabled in
                    QuietGramPresenceSettings.setHidden(enabled)
                })
"""),
]:
    text = once(text, anchor, before + anchor if before else anchor + "    case quietGram\n")
text = once(text, "        statePromise.get(),",
            "        combineLatest(statePromise.get(), QuietGramPresenceSettings.changes) |> map { state, _ in state },")
anchor = "    entries.append(.openLinksIn(presentationData.theme, presentationData.strings.ChatSettings_OpenLinksIn, defaultWebBrowser))"
text = once(text, anchor, anchor + "\n    entries.append(.quietOnline(QuietGramPresenceSettings.hidden))")
settings.write_text(text, encoding="utf-8")
print(f"Source ready: {root}. See README.md and versions.json inside it for Xcode setup.")
