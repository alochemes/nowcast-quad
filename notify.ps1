# Windows toast notification helper (no modules required).
# Usage: powershell -ExecutionPolicy Bypass -File notify.ps1 -Title "..." -Body "..."
param(
    [Parameter(Mandatory=$true)][string]$Title,
    [Parameter(Mandatory=$true)][string]$Body
)

try {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    $xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
        [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
    $texts = $xml.GetElementsByTagName("text")
    $texts.Item(0).AppendChild($xml.CreateTextNode($Title)) | Out-Null
    $texts.Item(1).AppendChild($xml.CreateTextNode($Body)) | Out-Null
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
    $appId = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
    Start-Sleep -Milliseconds 400   # let the toast dispatch before the process exits
} catch {
    Write-Output "toast failed: $($_.Exception.Message)"
    exit 1
}
