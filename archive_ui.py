# Applied by prepare.py to its pinned checkout, after the privacy switch.
text = presence.read_text(encoding="utf-8")
text = once(text, "import Foundation", "import Security\nimport Foundation")
text += r'''
public enum QuietArchivePairing {
    private static func query(_ account: Int64) -> [String: Any] {
        return [kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: "QuietGram.archive.v1",
                kSecAttrAccount as String: String(account)]
    }
    public static func get(_ account: Int64) -> [String]? {
        var q = query(account)
        q[kSecReturnData as String] = true
        var result: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return try? JSONDecoder().decode([String].self, from: data)
    }
    public static func save(_ account: Int64, _ url: String, _ key: String) -> Bool {
        let key = key.trimmingCharacters(in: .whitespacesAndNewlines).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        guard let u = URLComponents(string: url.trimmingCharacters(in: .whitespacesAndNewlines)),
              u.scheme == "https", let host = u.host, !host.isEmpty, u.user == nil, u.password == nil,
              u.port == nil, u.query == nil, u.fragment == nil, ["", "/", "/health"].contains(u.path),
              Data(base64Encoded: key)?.count == 32,
              let data = try? JSONEncoder().encode(["https://" + host, key]) else { return false }
        let q = query(account)
        let attrs: [String: Any] = [kSecValueData as String: data, kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly]
        let status = SecItemUpdate(q as CFDictionary, attrs as CFDictionary)
        if status == errSecItemNotFound {
            return SecItemAdd(q.merging(attrs) { _, new in new } as CFDictionary, nil) == errSecSuccess
        }
        return status == errSecSuccess
    }
    public static func clear(_ account: Int64) {
        SecItemDelete(query(account) as CFDictionary)
    }
}
'''
presence.write_text(text, encoding="utf-8")
text = settings.read_text(encoding="utf-8")
for anchor, before in [
    ("    case quietOnline(Bool)", "    case quietArchive\n"),
    ("        case .quietOnline:\n            return PrivacyAndSecuritySection", "        case .quietArchive:\n            return PrivacyAndSecuritySection.quietGram.rawValue\n"),
    ("            case .quietOnline:\n                return 34", "            case .quietArchive:\n                return 35\n"),
    ("            case let .quietOnline(value):\n                if case", "            case .quietArchive:\n                if case .quietArchive = rhs { return true }; return false\n"),
    ("            case let .quietOnline(value):\n                return ItemListSwitchItem", r'''            case .quietArchive:
                return ItemListDisclosureItem(presentationData: presentationData, systemStyle: .glass, title: "Архив удалённых", label: "", sectionId: self.section, style: .blocks, action: {
                    let account = arguments.account.peerId.id._internalGetInt64Value()
                    guard var presenter = UIApplication.shared.windows.first(where: { $0.isKeyWindow })?.rootViewController else { return }
                    while let next = presenter.presentedViewController { presenter = next }
                    let saved = QuietArchivePairing.get(account)
                    let box = UIAlertController(title: "Архив удалённых", message: "HTTPS-адрес туннеля и ключ с ноутбука", preferredStyle: .alert)
                    box.addTextField { $0.placeholder = "https://…"; $0.keyboardType = .URL; $0.autocapitalizationType = .none; $0.text = saved?.first }
                    box.addTextField { $0.placeholder = "Ключ"; $0.isSecureTextEntry = true }
                    box.addAction(UIAlertAction(title: "Сохранить", style: .default, handler: { _ in
                        let entered = box.textFields?[1].text ?? ""
                        let ok = QuietArchivePairing.save(account, box.textFields?[0].text ?? "", entered.isEmpty ? (saved?.last ?? "") : entered)
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                            let tip = UIAlertController(title: ok ? "Настройки сохранены" : "Проверь адрес и ключ", message: nil, preferredStyle: .alert)
                            tip.addAction(UIAlertAction(title: "OK", style: .default))
                            presenter.present(tip, animated: true)
                        }
                    }))
                    box.addAction(UIAlertAction(title: "Отключить", style: .destructive, handler: { _ in QuietArchivePairing.clear(account) }))
                    box.addAction(UIAlertAction(title: "Отмена", style: .cancel))
                    presenter.present(box, animated: true)
                })
'''),
]:
    text = once(text, anchor, before + anchor)
text = once(text, "    entries.append(.quietOnline(QuietGramPresenceSettings.hidden))",
            "    entries.append(.quietOnline(QuietGramPresenceSettings.hidden))\n    entries.append(.quietArchive)")
settings.write_text(text, encoding="utf-8")

history = root / "submodules/TelegramUI/Sources/ChatHistoryListNode.swift"
text = history.read_text(encoding="utf-8")
text = "import CryptoKit\n" + text
text += r'''
struct QuietArchiveRow: Decodable {
    let id: Int32
    let text: String
    let sent_at: Int32?
}
private struct QuietArchiveResult: Decodable {
    let account: Int64
    let chat: Int64
    let messages: [QuietArchiveRow]
}
private final class QuietNoRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
private func quietArchiveRead(_ account: PeerId, _ peer: PeerId) -> Signal<[QuietArchiveRow], NoError> {
    let aid = account.id._internalGetInt64Value()
    let raw = peer.id._internalGetInt64Value()
    let chat: Int64
    switch peer.namespace {
    case Namespaces.Peer.CloudUser: chat = raw
    case Namespaces.Peer.CloudGroup: chat = -raw
    case Namespaces.Peer.CloudChannel: chat = -1000000000000 - raw
    default: return .single([])
    }
    guard let parts = QuietArchivePairing.get(aid), parts.count == 2,
          let key = Data(base64Encoded: parts[1]) else { return .single([]) }
    let path = "/v1/deleted/\(aid)/\(chat)"
    guard let url = URL(string: parts[0] + path) else { return .single([]) }
    return Signal { subscriber in
        subscriber.putNext([])
        let token = CryptoKit.SHA256.hash(data: Data("QuietGram/archive-api/v1/auth\0".utf8) + key).map { String(format: "%02x", $0) }.joined()
        var req = URLRequest(url: url, timeoutInterval: 12)
        req.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        let session = URLSession(configuration: .ephemeral, delegate: QuietNoRedirect(), delegateQueue: nil)
        let task = session.dataTask(with: req) { data, response, _ in
            defer { subscriber.putCompletion(); session.finishTasksAndInvalidate() }
            guard (response as? HTTPURLResponse)?.statusCode == 200, let data = data,
                  let box = try? AES.GCM.SealedBox(combined: data),
                  let plaintext = try? AES.GCM.open(box, using: SymmetricKey(data: key), authenticating: Data(path.utf8)),
                  let parsed = try? JSONDecoder().decode(QuietArchiveResult.self, from: plaintext),
                  parsed.account == aid, parsed.chat == chat else { return }
            subscriber.putNext(parsed.messages)
        }
        task.resume()
        return ActionDisposable { session.invalidateAndCancel() }
    }
}
'''
anchor = "        let previousHistoryAppearsCleared = self.previousHistoryAppearsCleared"
text = once(text, anchor, """        let quietRows: Signal<[QuietArchiveRow], NoError>
        if case let .peer(peer) = chatLocation, subject == nil, tag == nil, mode == .bubbles {
            quietRows = quietArchiveRead(context.account.peerId, peer)
        } else { quietRows = .single([]) }
""" + anchor)
text = once(text, "            updatingMedia |> debug_measureTimeToFirstEvent", "            combineLatest(updatingMedia, quietRows) |> debug_measureTimeToFirstEvent")
text = once(text, "                    updatingMedia: updatingMedia,", "                    updatingMedia: updatingMedia.0,")
text = once(text, "                    currentState: previousChatHistoryEntriesForViewState,", "                    quietRows: updatingMedia.1,\n                    currentState: previousChatHistoryEntriesForViewState,")
history.write_text(text, encoding="utf-8")
entries = root / "submodules/TelegramUI/Sources/ChatHistoryEntriesForView.swift"
text = entries.read_text(encoding="utf-8")
text = once(text, "func chatHistoryEntriesForView(\n", "func chatHistoryEntriesForView(\n    quietRows: [QuietArchiveRow] = [],\n")
anchor = "    if isMusicPlaylist && entries.count == 1 {"
text = once(text, anchor, r'''    if case let .peer(peer) = location, !view.isLoading {
        let live = Set(view.entries.map { $0.message.id })
        var occupied = Set(entries.map { $0.stableId })
        for row in quietRows {
            guard let stamp = row.sent_at, row.id > 0,
                  !live.contains(MessageId(peerId: peer, namespace: Namespaces.Message.Cloud, id: row.id)) else { continue }
            if let low = view.entries.first, (view.earlierId != nil || view.holeEarlier), stamp < low.message.timestamp { continue }
            if let high = view.entries.last, (view.laterId != nil || view.holeLater), stamp > high.message.timestamp { continue }
            let m = Message(stableId: UInt32.max - UInt32(row.id), stableVersion: 0,
                id: MessageId(peerId: peer, namespace: -1, id: row.id), globallyUniqueId: nil, groupingKey: nil,
                groupInfo: nil, threadId: nil, timestamp: stamp, flags: [.Incoming], tags: [], globalTags: [],
                localTags: [], customTags: [], forwardInfo: nil, author: nil, text: "", attributes: [],
                media: [TelegramMediaAction(action: .customText(text: "Удалено · " + row.text, entities: [], additionalAttributes: nil))],
                peers: SimpleDictionary<PeerId, Peer>(), associatedMessages: SimpleDictionary<MessageId, Message>(),
                associatedMessageIds: [], associatedMedia: [:], associatedThreadInfo: nil, associatedStories: [:])
            let item = ChatHistoryEntry.MessageEntry(m, presentationData, true, nil, .none, ChatMessageEntryAttributes())
            if occupied.insert(item.stableId).inserted {
                entries.insert(item, at: entries.firstIndex(where: { $0.index.timestamp > stamp || ($0.index.timestamp == stamp && $0.index.id.id > row.id) }) ?? entries.endIndex)
            }
        }
    }
''' + anchor)
entries.write_text(text, encoding="utf-8")
