using System;
using System.Diagnostics;
using System.IO;

static class Launcher
{
    [STAThread]
    static void Main()
    {
        string dir = AppDomain.CurrentDomain.BaseDirectory;
        string script = Path.Combine(dir, "HubPanel.ps1");
        string repo = Environment.GetEnvironmentVariable("DEEPSEEK_HUB_REPO");
        if (string.IsNullOrWhiteSpace(repo)) repo = Directory.GetCurrentDirectory();
        var psi = new ProcessStartInfo("powershell.exe",
            "-NoProfile -STA -ExecutionPolicy Bypass -File \"" + script + "\" -Repo \"" + repo + "\"");
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        Process.Start(psi);
    }
}