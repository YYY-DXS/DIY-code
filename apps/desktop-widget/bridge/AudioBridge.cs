// AudioBridge: persistent stdin/stdout bridge for the desktop card.
// Protocol (one command per line):
//   list
//   set <pid> <0..1>
//   mute <pid> <0|1>
//   quit
// Every command writes one JSON line. Keeping the process alive avoids the
// ~second of WASAPI/COM startup on every slider click.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Text;

namespace AudioMixer
{
    [Guid("5CDF2C82-841E-4546-9722-0CF74078229A")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioEndpointVolume
    {
        int RegisterControlChangeNotify(IntPtr pNotify);
        int UnregisterControlChangeNotify(IntPtr pNotify);
        int GetChannelCount(out uint count);
        int SetMasterVolumeLevel(float level, ref Guid context);
        int SetMasterVolumeLevelScalar(float level, ref Guid context);
        int GetMasterVolumeLevel(out float level);
        int GetMasterVolumeLevelScalar(out float level);
        int SetChannelVolumeLevel(uint channel, float level, ref Guid context);
        int SetChannelVolumeLevelScalar(uint channel, float level, ref Guid context);
        int GetChannelVolumeLevel(uint channel, out float level);
        int GetChannelVolumeLevelScalar(uint channel, out float level);
        int SetMute(bool muted, ref Guid context);
        int GetMute(out bool muted);
        int GetVolumeStepInfo(out uint step, out uint stepCount);
        int VolumeStepUp(ref Guid context);
        int VolumeStepDown(ref Guid context);
        int QueryHardwareSupport(out uint mask);
        int GetVolumeRange(out float min, out float max, out float increment);
    }

    internal static class AudioMaster
    {
        private static IAudioEndpointVolume _endpoint;

        internal static IAudioEndpointVolume Endpoint()
        {
            if (_endpoint != null) return _endpoint;
            try
            {
                var enumerator = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject();
                IMMDevice device;
                if (enumerator.GetDefaultAudioEndpoint(0, 0, out device) != 0 || device == null)
                    return null;
                Guid iid = typeof(IAudioEndpointVolume).GUID;
                object obj;
                if (device.Activate(ref iid, 23, IntPtr.Zero, out obj) != 0 || obj == null)
                    return null;
                _endpoint = (IAudioEndpointVolume)obj;
            }
            catch
            {
                _endpoint = null;
            }
            return _endpoint;
        }

        internal static float? Volume()
        {
            IAudioEndpointVolume ep = Endpoint();
            if (ep == null) return null;
            float value;
            return ep.GetMasterVolumeLevelScalar(out value) == 0 ? (float?)value : null;
        }

        internal static bool? Muted()
        {
            IAudioEndpointVolume ep = Endpoint();
            if (ep == null) return null;
            bool value;
            return ep.GetMute(out value) == 0 ? (bool?)value : null;
        }

        internal static int SetVolume(float value)
        {
            IAudioEndpointVolume ep = Endpoint();
            if (ep == null) return 0;
            Guid context = Guid.Empty;
            return ep.SetMasterVolumeLevelScalar(Math.Max(0f, Math.Min(1f, value)), ref context) == 0 ? 1 : 0;
        }

        internal static int SetMute(bool muted)
        {
            IAudioEndpointVolume ep = Endpoint();
            if (ep == null) return 0;
            Guid context = Guid.Empty;
            return ep.SetMute(muted, ref context) == 0 ? 1 : 0;
        }
    }

    internal static class AudioBridge
    {
        [STAThread]
        private static int Main()
        {
            try
            {
                Console.OutputEncoding = new UTF8Encoding(false);
                Console.InputEncoding = new UTF8Encoding(false);
            }
            catch { }

            string line;
            while ((line = Console.ReadLine()) != null)
            {
                line = line.Trim();
                if (line.Length == 0) continue;
                if (line.Equals("quit", StringComparison.OrdinalIgnoreCase)) break;
                try
                {
                    if (line.Equals("list", StringComparison.OrdinalIgnoreCase))
                    {
                        WriteSnapshot();
                    }
                    else if (line.StartsWith("master ", StringComparison.OrdinalIgnoreCase))
                    {
                        string[] parts = line.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                        float level;
                        if (parts.Length >= 2 &&
                            float.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out level))
                        {
                            WriteSnapshot(AudioMaster.SetVolume(level));
                        }
                        else
                        {
                            WriteError("bad master command");
                        }
                    }
                    else if (line.StartsWith("mastermute ", StringComparison.OrdinalIgnoreCase))
                    {
                        string[] parts = line.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                        int muted;
                        if (parts.Length >= 2 &&
                            int.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out muted))
                        {
                            WriteSnapshot(AudioMaster.SetMute(muted != 0));
                        }
                        else
                        {
                            WriteError("bad mastermute command");
                        }
                    }
                    else if (line.StartsWith("set ", StringComparison.OrdinalIgnoreCase))
                    {
                        string[] parts = line.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                        int pid;
                        float volume;
                        if (parts.Length >= 3 &&
                            int.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out pid) &&
                            float.TryParse(parts[2], NumberStyles.Float, CultureInfo.InvariantCulture, out volume))
                        {
                            int changed = AudioSessions.SetVolume(pid, volume);
                            WriteSnapshot(changed);
                        }
                        else
                        {
                            WriteError("bad set command");
                        }
                    }
                    else if (line.StartsWith("mute ", StringComparison.OrdinalIgnoreCase))
                    {
                        string[] parts = line.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                        int pid;
                        int muted;
                        if (parts.Length >= 3 &&
                            int.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out pid) &&
                            int.TryParse(parts[2], NumberStyles.Integer, CultureInfo.InvariantCulture, out muted))
                        {
                            int changed = AudioSessions.SetMute(pid, muted != 0);
                            WriteSnapshot(changed);
                        }
                        else
                        {
                            WriteError("bad mute command");
                        }
                    }
                    else
                    {
                        WriteError("unknown command");
                    }
                }
                catch (Exception exc)
                {
                    WriteError(exc.Message);
                }
            }
            return 0;
        }

        private static void WriteSnapshot(int changed = 0)
        {
            List<SessionRow> rows = AudioSessions.Snapshot();
            float? master = AudioMaster.Volume();
            bool? muted = AudioMaster.Muted();
            StringBuilder json = new StringBuilder();
            json.Append("{\"ok\":true,\"device\":\"")
                .Append(Escape(AudioSessions.DefaultDeviceName()))
                .Append("\",\"changed\":").Append(changed.ToString(CultureInfo.InvariantCulture))
                .Append(",\"master\":")
                .Append(master.HasValue ? master.Value.ToString("0.###", CultureInfo.InvariantCulture) : "null")
                .Append(",\"masterMuted\":").Append(muted.HasValue && muted.Value ? "true" : "false")
                .Append(",\"sessions\":[");
            for (int i = 0; i < rows.Count; i++)
            {
                if (i > 0) json.Append(',');
                SessionRow row = rows[i];
                json.Append("{\"pid\":").Append(row.Pid.ToString(CultureInfo.InvariantCulture))
                    .Append(",\"name\":\"").Append(Escape(row.Name))
                    .Append("\",\"volume\":").Append(row.Volume.ToString("0.###", CultureInfo.InvariantCulture))
                    .Append(",\"muted\":").Append(row.Muted ? "true" : "false")
                    .Append(",\"active\":").Append(row.Active ? "true" : "false")
                    .Append(",\"peak\":").Append(row.Peak.ToString("0.###", CultureInfo.InvariantCulture))
                    .Append(",\"sessions\":").Append(row.SessionCount.ToString(CultureInfo.InvariantCulture))
                    .Append('}');
            }
            json.Append("]}");
            Console.WriteLine(json.ToString());
            Console.Out.Flush();
        }

        private static void WriteError(string message)
        {
            Console.WriteLine("{\"ok\":false,\"error\":\"" + Escape(message) + "\"}");
            Console.Out.Flush();
        }

        private static string Escape(string value)
        {
            if (string.IsNullOrEmpty(value)) return "";
            StringBuilder sb = new StringBuilder(value.Length + 8);
            foreach (char ch in value)
            {
                switch (ch)
                {
                    case '\\': sb.Append("\\\\"); break;
                    case '"': sb.Append("\\\""); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (ch < 32) sb.Append(' ');
                        else sb.Append(ch);
                        break;
                }
            }
            return sb.ToString();
        }
    }
}
