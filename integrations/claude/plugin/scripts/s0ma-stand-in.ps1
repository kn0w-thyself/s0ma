# s0ma-stand-in.ps1 - the stand-in s0ma server, for Windows.
#
# s0ma-serve.cmd starts this in Windows PowerShell (5.1, which every Windows
# has) when uv cannot run the launcher here. It is the twin of the stand-in at
# the end of scripts/s0ma-serve: it speaks just enough MCP, one JSON message per
# line, to say that s0ma is not set up on this machine yet, so the server never
# shows as failed. It offers the one setup-status tool the launcher's own setup
# helper offers, with the same name and wording, which a test holds it to.
#
# It installs nothing, downloads nothing, and opens no connection. Nothing but
# protocol goes to stdout, and it ends when stdin closes.

$ErrorActionPreference = 'Stop'

# The raw standard streams, in UTF-8 with no byte-order mark, rather than the
# console's own code page.
$utf8 = [System.Text.UTF8Encoding]::new($false)
$reader = [System.IO.StreamReader]::new([Console]::OpenStandardInput(), $utf8)
$writer = [System.IO.StreamWriter]::new([Console]::OpenStandardOutput(), $utf8)
$writer.NewLine = "`n"

# The message, from the one file that holds it.
$message = ''
try {
    $message = [System.IO.File]::ReadAllText((Join-Path $PSScriptRoot 'not-set-up.txt')).Trim()
} catch { }

$versions = @('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')

$serverInfo = [ordered]@{ name = 's0ma'; title = 's0ma (setup needed)'; version = '0.0.0-setup-stub' }
$tool = [ordered]@{
    name = 's0ma_setup_status'
    title = 's0ma setup status'
    description = 'Report whether s0ma is installed on this machine, which copy of s0ma would run in this project and why, and the one thing to do next. Reads a few files and changes nothing.'
    inputSchema = [ordered]@{ type = 'object'; properties = @{}; additionalProperties = $false }
    annotations = [ordered]@{
        title = 's0ma setup status'
        readOnlyHint = $true
        destructiveHint = $false
        idempotentHint = $true
        openWorldHint = $false
    }
}
$unknown = 'This server cannot do that. s0ma is not set up on this machine yet, so a stand-in is answering, and it only knows initialize, ping, tools/list and tools/call.'

function Send-Message($answer) {
    $writer.WriteLine((ConvertTo-Json -InputObject $answer -Compress -Depth 20))
    $writer.Flush()
}

while ($true) {
    $line = $reader.ReadLine()
    if ($null -eq $line) { break }
    if ($line.Trim() -eq '') { continue }
    try { $request = ConvertFrom-Json -InputObject $line } catch { continue }
    if ($request -isnot [System.Management.Automation.PSCustomObject]) { continue }
    $names = @($request.PSObject.Properties | ForEach-Object { $_.Name })
    if (($names -notcontains 'method') -or ($names -notcontains 'id')) { continue }
    $id = $request.id
    $method = [string]$request.method

    if ($method -eq 'initialize') {
        $asked = $null
        if ($null -ne $request.params) { $asked = $request.params.protocolVersion }
        $version = $versions[0]
        if (($asked -is [string]) -and ($versions -contains $asked)) { $version = $asked }
        $result = [ordered]@{
            protocolVersion = $version
            capabilities = [ordered]@{ tools = @{} }
            serverInfo = $serverInfo
            instructions = $message
        }
        Send-Message ([ordered]@{ jsonrpc = '2.0'; id = $id; result = $result })
    } elseif ($method -eq 'ping') {
        Send-Message ([ordered]@{ jsonrpc = '2.0'; id = $id; result = @{} })
    } elseif ($method -eq 'tools/list') {
        Send-Message ([ordered]@{ jsonrpc = '2.0'; id = $id; result = [ordered]@{ tools = @($tool) } })
    } elseif ($method -eq 'tools/call') {
        $content = @([ordered]@{ type = 'text'; text = $message })
        Send-Message ([ordered]@{ jsonrpc = '2.0'; id = $id; result = [ordered]@{ content = $content; isError = $false } })
    } else {
        $failure = [ordered]@{ code = -32601; message = $unknown }
        Send-Message ([ordered]@{ jsonrpc = '2.0'; id = $id; error = $failure })
    }
}
exit 0
