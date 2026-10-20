param(
    [string]$Path,
    [string]$JsonPath
)
# export_reports.py 가 부르는 엑셀 쓰기 도구. 시트가 없으면 만들고, 이미 있는 제보ID(A열)는 건너뛰고 새 제보만 맨 아래에 추가한다.
# 글자는 JSON 에서 읽고(한글이 스크립트 인코딩에 영향을 받지 않게), 삭제는 하지 않는다.
$ErrorActionPreference = "Stop"

function Invoke-Retry([scriptblock]$Action, [int]$Tries = 20) {
    for ($i = 1; $i -le $Tries; $i++) {
        try { return & $Action }
        catch {
            if ($_.Exception.HResult -eq -2147418111 -and $i -lt $Tries) { Start-Sleep -Milliseconds 700; continue }
            throw
        }
    }
}

# 엑셀이 파일을 열고 있으면 쓰지 않는다 (사용자의 편집을 덮어쓰지 않기 위해)
try {
    $fs = [System.IO.File]::Open($Path, 'Open', 'ReadWrite', 'None'); $fs.Close()
} catch {
    Write-Output "LOCKED: the workbook is open in Excel. Close it and run again. Nothing was changed."
    exit 2
}

$json = [System.IO.File]::ReadAllText($JsonPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
$xl = New-Object -ComObject Excel.Application
$wb = $null
try {
    Start-Sleep -Seconds 2
    Invoke-Retry { $xl.Visible = $false }
    Invoke-Retry { $xl.DisplayAlerts = $false }
    Invoke-Retry { $xl.AutomationSecurity = 3 }
    Invoke-Retry { $xl.EnableEvents = $false }
    $wb = Invoke-Retry { $xl.Workbooks.Open($Path, 0, $false) }

    foreach ($sheet in $json.sheets) {
        $ws = $null
        foreach ($s in $wb.Worksheets) { if ($s.Name -eq $sheet.name) { $ws = $s } }
        $created = $false
        if (-not $ws) {
            $last = $wb.Worksheets.Item($wb.Worksheets.Count)
            $ws = $wb.Worksheets.Add([System.Type]::Missing, $last)
            $ws.Name = $sheet.name
            $created = $true
            $cols = $sheet.headers.Count
            $hdr = New-Object 'object[,]' 1, $cols
            for ($c = 0; $c -lt $cols; $c++) { $hdr[0, $c] = [string]$sheet.headers[$c] }
            $ws.Range($ws.Cells.Item(1, 1), $ws.Cells.Item(1, $cols)).Value2 = $hdr
            $ws.Range($ws.Cells.Item(1, 1), $ws.Cells.Item(1, $cols)).Font.Bold = $true
            $ws.Columns.Item(1).NumberFormat = "@"   # 제보ID 는 글자로
            $ws.Columns.Item(2).NumberFormat = "@"
        }

        # 이미 있는 제보ID
        $existing = @{}
        $lastRow = $ws.UsedRange.Rows.Count
        if ($lastRow -ge 2) {
            $ids = $ws.Range("A2:A$lastRow").Value2
            if ($ids -is [array]) { foreach ($v in $ids) { if ($v) { $existing[[string]$v] = $true } } }
            elseif ($ids) { $existing[[string]$ids] = $true }
        }

        $newRows = @($sheet.rows | Where-Object { -not $existing.ContainsKey([string]$_[0]) })
        if ($newRows.Count -gt 0) {
            $cols = $sheet.headers.Count
            $arr = New-Object 'object[,]' $newRows.Count, $cols
            for ($r = 0; $r -lt $newRows.Count; $r++) {
                for ($c = 0; $c -lt $cols; $c++) { $arr[$r, $c] = $newRows[$r][$c] }
            }
            $startRow = $lastRow + 1
            if ($lastRow -lt 1) { $startRow = 2 }
            $endRow = $startRow + $newRows.Count - 1
            $ws.Range($ws.Cells.Item($startRow, 1), $ws.Cells.Item($endRow, $cols)).Value2 = $arr
        }
        $state = "existing"; if ($created) { $state = "created" }
        Write-Output ("sheet '" + $sheet.name + "': " + $state + ", added " + $newRows.Count + ", skipped " + ($sheet.rows.Count - $newRows.Count))
    }
    Invoke-Retry { $wb.Save() } | Out-Null
    Write-Output "saved"
}
finally {
    if ($wb) { try { $wb.Close($false) } catch {} }
    try { $xl.Quit() } catch {}
    try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null } catch {}
}
