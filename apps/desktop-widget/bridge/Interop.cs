// Windows Core Audio (WASAPI) session access for the mixer.
//
// Only the COM pieces this app needs are declared, and always in exact vtable
// order starting at the first slot, because an interface declared out of order
// silently calls the neighbouring method instead.
//
//   IMMDeviceEnumerator  -> default render endpoint
//   IMMDevice::Activate  -> IAudioSessionManager2
//   IAudioSessionManager2::GetSessionEnumerator -> per-session ISimpleAudioVolume
//
// Session volume, mute and peak meters are read per session, then folded into
// one row per process: that is the unit Windows' own mixer calls an application,
// and it is what makes Edge and QQ Music independent rows here.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

namespace AudioMixer
{
    internal static class Native
    {
        public const int EDataFlowRender = 0;
        public const int ERoleConsole = 0;
        public const int CLSCTX_ALL = 23;

        public const int WM_NCLBUTTONDOWN = 0xA1;
        public const int HTCAPTION = 2;

        [DllImport("user32.dll")]
        public static extern bool ReleaseCapture();

        [DllImport("user32.dll")]
        public static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);
    }

    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    internal class MMDeviceEnumeratorComObject
    {
    }

    [Guid("A95664D2-9614-4F35-A746-DE8DB63617E6")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMMDeviceEnumerator
    {
        int EnumAudioEndpoints(int dataFlow, int stateMask, out IntPtr devices);
        int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice device);
        int GetDevice([MarshalAs(UnmanagedType.LPWStr)] string id, out IMMDevice device);
        int RegisterEndpointNotificationCallback(IntPtr client);
        int UnregisterEndpointNotificationCallback(IntPtr client);
    }

    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    internal struct PROPERTYKEY
    {
        public Guid fmtid;
        public int pid;
    }

    /// <summary>
    /// A fixed-size PROPVARIANT. The union is read at offset 8 on both
    /// architectures; the declared size is deliberately larger than either
    /// real struct so the callee can never write past what we allocated.
    /// </summary>
    [StructLayout(LayoutKind.Explicit, Size = 32)]
    internal struct PROPVARIANT
    {
        [FieldOffset(0)] public short vt;
        [FieldOffset(2)] public short wReserved1;
        [FieldOffset(4)] public short wReserved2;
        [FieldOffset(6)] public short wReserved3;
        [FieldOffset(8)] public IntPtr pointerValue;
    }

    [Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IPropertyStore
    {
        int GetCount(out int count);
        int GetAt(int index, out PROPERTYKEY key);
        int GetValue(ref PROPERTYKEY key, out PROPVARIANT value);
        int SetValue(ref PROPERTYKEY key, ref PROPVARIANT value);
        int Commit();
    }

    [Guid("D666063F-1587-4E43-81F1-B948E807363F")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMMDevice
    {
        int Activate(ref Guid iid, int clsCtx, IntPtr activationParams,
            [MarshalAs(UnmanagedType.IUnknown)] out object iface);
        int OpenPropertyStore(int access, out IPropertyStore properties);
        int GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
        int GetState(out int state);
    }

    [Guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioSessionManager2
    {
        int GetAudioSessionControl(ref Guid audioSessionGuid, int streamFlags, out IntPtr session);
        int GetSimpleAudioVolume(ref Guid audioSessionGuid, int streamFlags, out IntPtr volume);
        int GetSessionEnumerator(out IAudioSessionEnumerator enumerator);
        int RegisterSessionNotification(IntPtr notification);
        int UnregisterSessionNotification(IntPtr notification);
    }

    [Guid("E2F5BB11-0570-40CA-ACDD-3AA01277DEE8")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioSessionEnumerator
    {
        int GetCount(out int count);
        int GetSession(int index, out IAudioSessionControl session);
    }

    /// <summary>IAudioSessionControl, declared flat so the slot order is explicit.</summary>
    [Guid("F4B1A599-7266-4319-A8CA-E70ACB11E8CD")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioSessionControl
    {
        int GetState(out int state);
        int GetDisplayName([MarshalAs(UnmanagedType.LPWStr)] out string name);
        int SetDisplayName([MarshalAs(UnmanagedType.LPWStr)] string name, ref Guid eventContext);
        int GetIconPath([MarshalAs(UnmanagedType.LPWStr)] out string path);
        int SetIconPath([MarshalAs(UnmanagedType.LPWStr)] string path, ref Guid eventContext);
        int GetGroupingParam(out Guid groupingParam);
        int SetGroupingParam(ref Guid groupingParam, ref Guid eventContext);
        int RegisterAudioSessionNotification(IntPtr notification);
        int UnregisterAudioSessionNotification(IntPtr notification);
    }

    /// <summary>IAudioSessionControl2: the nine base slots, then the five it adds.</summary>
    [Guid("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioSessionControl2
    {
        int GetState(out int state);
        int GetDisplayName([MarshalAs(UnmanagedType.LPWStr)] out string name);
        int SetDisplayName([MarshalAs(UnmanagedType.LPWStr)] string name, ref Guid eventContext);
        int GetIconPath([MarshalAs(UnmanagedType.LPWStr)] out string path);
        int SetIconPath([MarshalAs(UnmanagedType.LPWStr)] string path, ref Guid eventContext);
        int GetGroupingParam(out Guid groupingParam);
        int SetGroupingParam(ref Guid groupingParam, ref Guid eventContext);
        int RegisterAudioSessionNotification(IntPtr notification);
        int UnregisterAudioSessionNotification(IntPtr notification);
        int GetSessionIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string id);
        int GetSessionInstanceIdentifier([MarshalAs(UnmanagedType.LPWStr)] out string id);
        int GetProcessId(out int pid);
        // S_FALSE (1) means "not the system sounds session", so the HRESULT is kept raw.
        [PreserveSig] int IsSystemSoundsSession();
        int SetDuckingPreference(bool enable);
    }

    [Guid("87CE5498-68D6-44E5-9215-6DA47EF883D8")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface ISimpleAudioVolume
    {
        int SetMasterVolume(float level, ref Guid eventContext);
        int GetMasterVolume(out float level);
        int SetMute(bool mute, ref Guid eventContext);
        int GetMute(out bool mute);
    }

    [Guid("C02216F6-8C67-4B5B-9D00-D008E73E0064")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IAudioMeterInformation
    {
        int GetPeakValue(out float peak);
        int GetMeteringChannelCount(out int channelCount);
        int GetChannelsPeakValues(int channelCount, [Out] float[] peaks);
        int QueryHardwareSupport(out int mask);
    }

    internal static class PropertyKeys
    {
        /// <summary>PKEY_Device_* share one format id; only the pid differs.</summary>
        public static readonly Guid DevicePropertyFormat =
            new Guid("a45c254e-df1c-4efd-8020-67d146a850e0");
        public const int DeviceDescription = 2;
        public const int DeviceFriendlyName = 14;
    }

    /// <summary>One application's audio state, folded from all of its sessions.</summary>
    internal sealed class SessionRow
    {
        public int Pid;
        public string Name;
        public string ExePath;
        public bool IsSystemSounds;
        public float Volume;
        public bool Muted;
        public float Peak;
        public bool Active;
        public int SessionCount;
    }

    internal static class AudioSessions
    {
        private static readonly Guid IID_IAudioSessionManager2 =
            new Guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F");

        /// <summary>Friendly names for the executables people actually see.</summary>
        private static readonly Dictionary<string, string> Friendly = BuildFriendly();

        private static Dictionary<string, string> BuildFriendly()
        {
            Dictionary<string, string> map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            map["msedge"] = "Microsoft Edge";
            map["chrome"] = "Google Chrome";
            map["firefox"] = "Firefox";
            map["brave"] = "Brave";
            map["opera"] = "Opera";
            map["qqmusic"] = "QQ音乐";
            map["cloudmusic"] = "网易云音乐";
            map["spotify"] = "Spotify";
            map["discord"] = "Discord";
            map["wechat"] = "微信";
            map["weixin"] = "微信";
            map["telegram"] = "Telegram";
            map["potplayermini64"] = "PotPlayer";
            map["vlc"] = "VLC";
            map["code"] = "Visual Studio Code";
            map["windowsterminal"] = "Windows Terminal";
            map["powershell"] = "PowerShell";
            map["pwsh"] = "PowerShell";
            map["deepseek harness"] = "DeepSeek Harness";
            map["explorer"] = "资源管理器";
            map["systemsettings"] = "设置";
            return map;
        }

        private static IAudioSessionEnumerator OpenEnumerator()
        {
            IMMDeviceEnumerator devices = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject();
            IMMDevice device;
            int hr = devices.GetDefaultAudioEndpoint(Native.EDataFlowRender, Native.ERoleConsole, out device);
            if (hr != 0 || device == null)
            {
                throw new InvalidOperationException("no default render device (HRESULT 0x" + hr.ToString("X8") + ")");
            }
            object activated;
            Guid iid = IID_IAudioSessionManager2;
            hr = device.Activate(ref iid, Native.CLSCTX_ALL, IntPtr.Zero, out activated);
            if (hr != 0 || activated == null)
            {
                throw new InvalidOperationException("cannot activate the session manager (HRESULT 0x" + hr.ToString("X8") + ")");
            }
            IAudioSessionManager2 manager = (IAudioSessionManager2)activated;
            IAudioSessionEnumerator sessions;
            hr = manager.GetSessionEnumerator(out sessions);
            if (hr != 0 || sessions == null)
            {
                throw new InvalidOperationException("cannot enumerate audio sessions (HRESULT 0x" + hr.ToString("X8") + ")");
            }
            return sessions;
        }

        /// <summary>Name of the default output device, for the header line.</summary>
        public static string DefaultDeviceName()
        {
            try
            {
                IMMDeviceEnumerator devices = (IMMDeviceEnumerator)new MMDeviceEnumeratorComObject();
                IMMDevice device;
                if (devices.GetDefaultAudioEndpoint(Native.EDataFlowRender, Native.ERoleConsole, out device) != 0)
                {
                    return "";
                }
                IPropertyStore store;
                // STGM_READ = 0
                if (device.OpenPropertyStore(0, out store) != 0 || store == null)
                {
                    return "";
                }
                string name = ReadStringProperty(store, PropertyKeys.DevicePropertyFormat, PropertyKeys.DeviceFriendlyName);
                if (name.Length == 0)
                {
                    name = ReadStringProperty(store, PropertyKeys.DevicePropertyFormat, PropertyKeys.DeviceDescription);
                }
                return name;
            }
            catch
            {
                return "";
            }
        }

        /// <summary>Read one string from a property store, freeing the PROPVARIANT.</summary>
        private static string ReadStringProperty(IPropertyStore store, Guid formatId, int propertyId)
        {
            PROPERTYKEY key = new PROPERTYKEY();
            key.fmtid = formatId;
            key.pid = propertyId;
            PROPVARIANT value;
            if (store.GetValue(ref key, out value) != 0)
            {
                return "";
            }
            string text = "";
            try
            {
                // VT_LPWSTR = 31
                if (value.vt == 31 && value.pointerValue != IntPtr.Zero)
                {
                    text = Marshal.PtrToStringUni(value.pointerValue);
                    if (text == null)
                    {
                        text = "";
                    }
                }
            }
            finally
            {
                try
                {
                    PropVariantClear(ref value);
                }
                catch
                {
                }
            }
            return text.Trim();
        }

        [DllImport("ole32.dll")]
        private static extern int PropVariantClear(ref PROPVARIANT value);

        /// <summary>
        /// Read every session and fold it into one row per process. Expired
        /// sessions are dropped; the system-sounds session has pid 0.
        /// </summary>
        public static List<SessionRow> Snapshot()
        {
            List<SessionRow> rows = new List<SessionRow>();
            IAudioSessionEnumerator sessions;
            try
            {
                sessions = OpenEnumerator();
            }
            catch
            {
                return rows;
            }

            Dictionary<int, SessionRow> byPid = new Dictionary<int, SessionRow>();
            int count = 0;
            try
            {
                sessions.GetCount(out count);
            }
            catch
            {
                return rows;
            }

            for (int index = 0; index < count; index++)
            {
                IAudioSessionControl control = null;
                try
                {
                    if (sessions.GetSession(index, out control) != 0)
                    {
                        continue;
                    }
                    IAudioSessionControl2 details = control as IAudioSessionControl2;
                    if (details == null)
                    {
                        continue;
                    }

                    int state;
                    details.GetState(out state);
                    if (state == 2)
                    {
                        continue;
                    }

                    int pid;
                    details.GetProcessId(out pid);
                    bool isSystem = details.IsSystemSoundsSession() == 0;

                    ISimpleAudioVolume volume = control as ISimpleAudioVolume;
                    if (volume == null)
                    {
                        continue;
                    }
                    float level;
                    if (volume.GetMasterVolume(out level) != 0)
                    {
                        level = 1f;
                    }
                    bool muted = false;
                    volume.GetMute(out muted);

                    float peak = 0f;
                    IAudioMeterInformation meter = control as IAudioMeterInformation;
                    if (meter != null)
                    {
                        try
                        {
                            meter.GetPeakValue(out peak);
                        }
                        catch
                        {
                            peak = 0f;
                        }
                    }

                    SessionRow row;
                    if (!byPid.TryGetValue(pid, out row))
                    {
                        row = new SessionRow();
                        row.Pid = pid;
                        row.IsSystemSounds = isSystem;
                        row.Volume = level;
                        row.Muted = muted;
                        row.Peak = peak;
                        row.Active = state == 1;
                        row.SessionCount = 1;
                        row.Name = isSystem ? "系统声音" : NameFor(pid, details);
                        row.ExePath = isSystem ? "" : PathFor(pid, details);
                        byPid.Add(pid, row);
                    }
                    else
                    {
                        row.SessionCount++;
                        if (level > row.Volume)
                        {
                            row.Volume = level;
                        }
                        if (muted)
                        {
                            row.Muted = true;
                        }
                        if (peak > row.Peak)
                        {
                            row.Peak = peak;
                        }
                        if (state == 1)
                        {
                            row.Active = true;
                        }
                    }
                }
                catch
                {
                    // One unreadable session must not hide the others.
                }
                finally
                {
                    Release(control);
                }
            }

            foreach (SessionRow row in byPid.Values)
            {
                rows.Add(row);
            }
            rows.Sort(CompareRows);
            return rows;
        }

        private static int CompareRows(SessionRow a, SessionRow b)
        {
            if (a.Active != b.Active)
            {
                return a.Active ? -1 : 1;
            }
            if (a.IsSystemSounds != b.IsSystemSounds)
            {
                return a.IsSystemSounds ? 1 : -1;
            }
            return string.Compare(a.Name, b.Name, StringComparison.CurrentCultureIgnoreCase);
        }

        /// <summary>Set one application's volume; returns how many sessions moved.</summary>
        public static int SetVolume(int pid, float level)
        {
            if (level < 0f)
            {
                level = 0f;
            }
            if (level > 1f)
            {
                level = 1f;
            }
            Guid context = Guid.Empty;
            int changed = 0;
            IAudioSessionEnumerator sessions;
            try
            {
                sessions = OpenEnumerator();
            }
            catch
            {
                return 0;
            }
            int count = 0;
            sessions.GetCount(out count);
            for (int index = 0; index < count; index++)
            {
                IAudioSessionControl control = null;
                try
                {
                    if (sessions.GetSession(index, out control) != 0)
                    {
                        continue;
                    }
                    IAudioSessionControl2 details = control as IAudioSessionControl2;
                    if (details == null)
                    {
                        continue;
                    }
                    int sessionPid;
                    details.GetProcessId(out sessionPid);
                    if (sessionPid != pid)
                    {
                        continue;
                    }
                    ISimpleAudioVolume volume = control as ISimpleAudioVolume;
                    if (volume == null)
                    {
                        continue;
                    }
                    if (volume.SetMasterVolume(level, ref context) == 0)
                    {
                        changed++;
                    }
                }
                catch
                {
                }
                finally
                {
                    Release(control);
                }
            }
            return changed;
        }

        /// <summary>Set one application's mute; returns how many sessions moved.</summary>
        public static int SetMute(int pid, bool muted)
        {
            Guid context = Guid.Empty;
            int changed = 0;
            IAudioSessionEnumerator sessions;
            try
            {
                sessions = OpenEnumerator();
            }
            catch
            {
                return 0;
            }
            int count = 0;
            sessions.GetCount(out count);
            for (int index = 0; index < count; index++)
            {
                IAudioSessionControl control = null;
                try
                {
                    if (sessions.GetSession(index, out control) != 0)
                    {
                        continue;
                    }
                    IAudioSessionControl2 details = control as IAudioSessionControl2;
                    if (details == null)
                    {
                        continue;
                    }
                    int sessionPid;
                    details.GetProcessId(out sessionPid);
                    if (sessionPid != pid)
                    {
                        continue;
                    }
                    ISimpleAudioVolume volume = control as ISimpleAudioVolume;
                    if (volume == null)
                    {
                        continue;
                    }
                    if (volume.SetMute(muted, ref context) == 0)
                    {
                        changed++;
                    }
                }
                catch
                {
                }
                finally
                {
                    Release(control);
                }
            }
            return changed;
        }

        /// <summary>
        /// The executable behind a session, in Win32 form.
        ///
        /// The session identifier is tried first: it holds the NT path of the
        /// executable and works for processes whose Process handle is denied
        /// (another integrity level), where MainModule throws. The process API
        /// is the fallback for sessions that expose no path.
        /// </summary>
        private static string PathFor(int pid, IAudioSessionControl2 details)
        {
            string identifier = null;
            try
            {
                details.GetSessionIdentifier(out identifier);
            }
            catch
            {
                identifier = null;
            }
            string path = Win32PathFromIdentifier(identifier);
            if (path.Length > 0 && File.Exists(path))
            {
                return path;
            }
            string fromProcess = ProcessPathFor(pid);
            if (fromProcess.Length > 0)
            {
                return fromProcess;
            }
            return path;
        }

        /// <summary>Display name for a session's process, preferring the file name.</summary>
        private static string NameFor(int pid, IAudioSessionControl2 details)
        {
            string path = PathFor(pid, details);
            if (path.Length > 0)
            {
                string stem = System.IO.Path.GetFileNameWithoutExtension(path);
                if (!string.IsNullOrEmpty(stem))
                {
                    string friendly;
                    if (Friendly.TryGetValue(stem, out friendly))
                    {
                        return friendly;
                    }
                    return stem;
                }
            }
            return ProcessNameFor(pid);
        }

        /// <summary>
        /// Pull the Win32 path out of
        /// "{0.0.0.0}.{device}|\Device\HarddiskVolume3\...\app.exe%b{context}".
        /// </summary>
        private static string Win32PathFromIdentifier(string identifier)
        {
            if (string.IsNullOrEmpty(identifier))
            {
                return "";
            }
            int pipe = identifier.IndexOf('|');
            if (pipe < 0 || pipe + 1 >= identifier.Length)
            {
                return "";
            }
            string rest = identifier.Substring(pipe + 1);
            int marker = rest.IndexOf("%b", StringComparison.Ordinal);
            if (marker >= 0)
            {
                rest = rest.Substring(0, marker);
            }
            rest = rest.Trim();
            if (rest.Length < 2 || rest[0] != '\\')
            {
                return "";
            }
            return FromNtPath(rest);
        }

        private static readonly Dictionary<string, string> DeviceMap =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        /// <summary>Map "\Device\HarddiskVolumeN" prefixes to drive letters.</summary>
        private static string FromNtPath(string ntPath)
        {
            lock (DeviceMap)
            {
                if (DeviceMap.Count == 0)
                {
                    for (char letter = 'A'; letter <= 'Z'; letter++)
                    {
                        StringBuilder buffer = new StringBuilder(2048);
                        if (QueryDosDevice(letter.ToString() + ":", buffer, buffer.Capacity) != 0)
                        {
                            string target = buffer.ToString();
                            if (target.StartsWith("\\Device\\", StringComparison.OrdinalIgnoreCase))
                            {
                                DeviceMap[target] = letter.ToString() + ":";
                            }
                        }
                    }
                }
            }
            lock (DeviceMap)
            {
                foreach (KeyValuePair<string, string> pair in DeviceMap)
                {
                    if (ntPath.StartsWith(pair.Key, StringComparison.OrdinalIgnoreCase))
                    {
                        return pair.Value + ntPath.Substring(pair.Key.Length);
                    }
                }
            }
            return ntPath;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern int QueryDosDevice(string deviceName, StringBuilder targetPath, int max);

        private static string ProcessNameFor(int pid)
        {
            if (pid == 0)
            {
                return "系统声音";
            }
            try
            {
                using (Process process = Process.GetProcessById(pid))
                {
                    string name = process.ProcessName;
                    string friendly;
                    if (Friendly.TryGetValue(name, out friendly))
                    {
                        return friendly;
                    }
                    return name;
                }
            }
            catch
            {
                return "进程 " + pid.ToString();
            }
        }

        private static string ProcessPathFor(int pid)
        {
            if (pid == 0)
            {
                return "";
            }
            try
            {
                using (Process process = Process.GetProcessById(pid))
                {
                    return process.MainModule.FileName;
                }
            }
            catch
            {
                return "";
            }
        }

        private static void Release(object comObject)
        {
            if (comObject == null)
            {
                return;
            }
            try
            {
                if (Marshal.IsComObject(comObject))
                {
                    Marshal.ReleaseComObject(comObject);
                }
            }
            catch
            {
            }
        }
    }
}
