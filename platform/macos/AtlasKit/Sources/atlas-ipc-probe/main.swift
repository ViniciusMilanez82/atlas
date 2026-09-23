import AtlasKit
import Foundation

// Cross-language contract probe: a Swift client talks to the Python atlas-core over the Unix socket.
// usage: atlas-ipc-probe <socket-path> <token-file> <employee-id>
// The token is read from a 0600 file, never from the command line.

let args = CommandLine.arguments
guard args.count == 4 else {
    FileHandle.standardError.write(Data("usage: atlas-ipc-probe <socket-path> <token-file> <employee-id>\n".utf8))
    exit(2)
}

do {
    let token = try String(contentsOfFile: args[2], encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
    let client = try IPCClient(socketPath: args[1])
    try client.hello(token: token)
    let health = try client.call("system.health", params: [:])
    let created = try client.call("tasks.create", params: [
        "employee_id": args[3],
        "objective": "Tarefa criada pelo cliente Swift",
        "artifact_ids": [String](),
        "constraints": ["external_writes": false, "purchases": false],
    ])
    let forged = try client.call("tasks.list", params: ["employee_id": args[3], "actor": "owner"])
    let result: [String: Any] = ["health": health, "created": created, "forged": forged]
    let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
} catch {
    FileHandle.standardError.write(Data("probe failed: \(error)\n".utf8))
    exit(1)
}
