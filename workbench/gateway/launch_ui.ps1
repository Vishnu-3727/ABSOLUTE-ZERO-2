# Opens the ABSOLUTE-ZERO-2 dashboard; boots the workbench gateway first
# if it is not already listening. Desktop shortcut points here.
$ErrorActionPreference = 'SilentlyContinue'
$port = 8777

function Test-Port {
    $t = New-Object Net.Sockets.TcpClient
    try { $t.Connect('127.0.0.1', $port); return $t.Connected }
    catch { return $false }
    finally { $t.Close() }
}

if (-not (Test-Port)) {
    Start-Process pythonw -ArgumentList '-m', 'uvicorn', 'main:app', '--port', "$port" `
        -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
    foreach ($i in 1..40) {
        Start-Sleep -Milliseconds 250
        if (Test-Port) { break }
    }
}

Start-Process "http://127.0.0.1:$port/"
