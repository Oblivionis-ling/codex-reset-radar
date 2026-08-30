from __future__ import annotations

import base64
import subprocess


class WindowsNotificationError(RuntimeError):
    """Raised when the local Windows Toast command fails."""


class WindowsToastNotifier:
    app_id = "Codex.Reset.Radar"

    def __init__(self, *, timeout: float = 10.0):
        self.timeout = timeout

    def send(self, title: str, content: str) -> None:
        title_b64 = base64.b64encode(title.encode("utf-8")).decode("ascii")
        content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        script = f"""
$title = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{title_b64}'))
$content = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{content_b64}'))
$safeTitle = [System.Security.SecurityElement]::Escape($title)
$safeContent = [System.Security.SecurityElement]::Escape($content)
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$safeTitle</text><text>$safeContent</text></binding></visual></toast>")
$toast = New-Object Windows.UI.Notifications.ToastNotification($xml)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{self.app_id}')
$notifier.Show($toast)
"""
        encoded_script = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-EncodedCommand",
                    encoded_script,
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WindowsNotificationError(f"local Toast command failed: {exc.__class__.__name__}") from exc
        if result.returncode != 0:
            detail = (result.stderr or "").strip().replace("\r", " ").replace("\n", " ")[:240]
            raise WindowsNotificationError(detail or f"PowerShell exited with {result.returncode}")
