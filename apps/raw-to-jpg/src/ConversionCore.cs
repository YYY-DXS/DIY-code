using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace Raw2JpgStudio
{
    public enum ConflictPolicy
    {
        Rename,
        Skip,
        Overwrite
    }

    public sealed class ConversionOptions
    {
        public string OutputDirectory { get; set; }
        public bool SaveBesideOriginals { get; set; }
        public int JpegQuality { get; set; }
        public int MaxSize { get; set; }
        public bool AllowEmbeddedPreview { get; set; }
        public ConflictPolicy ConflictPolicy { get; set; }

        public ConversionOptions()
        {
            JpegQuality = 92;
            MaxSize = 0;
            AllowEmbeddedPreview = true;
            ConflictPolicy = ConflictPolicy.Rename;
        }
    }

    public sealed class ConversionProgress
    {
        public int Current { get; set; }
        public int Total { get; set; }
        public string FilePath { get; set; }
        public FileConversionResult Result { get; set; }
    }

    public sealed class FileConversionResult
    {
        public string SourcePath { get; set; }
        public string OutputPath { get; set; }
        public bool Success { get; set; }
        public bool Skipped { get; set; }
        public bool UsedEmbeddedPreview { get; set; }
        public string Error { get; set; }
    }

    public sealed class ConversionSummary
    {
        public int Total { get; set; }
        public int Succeeded { get; set; }
        public int Failed { get; set; }
        public int Skipped { get; set; }
        public int PreviewFallbacks { get; set; }
        public bool Cancelled { get; set; }
        public List<FileConversionResult> Results { get; private set; }

        public ConversionSummary()
        {
            Results = new List<FileConversionResult>();
        }
    }

    public sealed class PreviewDecodeResult
    {
        public BitmapSource Image { get; set; }
        public int SourceWidth { get; set; }
        public int SourceHeight { get; set; }
        public bool UsedEmbeddedPreview { get; set; }
    }

    public sealed class RawDecodeException : Exception
    {
        public RawDecodeException(string message, Exception innerException)
            : base(message, innerException)
        {
        }
    }

    public static class SupportedFormats
    {
        public static readonly HashSet<string> RawExtensions =
            new HashSet<string>(
                new string[]
                {
                    ".3fr", ".ari", ".arw", ".bay", ".cap", ".cr2", ".cr3",
                    ".crw", ".dcr", ".dcs", ".dng", ".drf", ".eip", ".erf",
                    ".fff", ".iiq", ".k25", ".kdc", ".mdp", ".mef", ".mos",
                    ".mrw", ".nef", ".nrw", ".orf", ".pef", ".pxn", ".r3d",
                    ".raf", ".raw", ".rw2", ".rwl", ".rwz", ".sr2", ".srf",
                    ".srw", ".sti", ".x3f"
                },
                StringComparer.OrdinalIgnoreCase);

        public static readonly HashSet<string> ImageExtensions =
            new HashSet<string>(
                new string[]
                {
                    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff",
                    ".webp"
                },
                StringComparer.OrdinalIgnoreCase);

        public static bool IsRaw(string path)
        {
            return path != null && RawExtensions.Contains(Path.GetExtension(path));
        }

        public static bool IsSupported(string path)
        {
            if (String.IsNullOrWhiteSpace(path))
            {
                return false;
            }

            string extension = Path.GetExtension(path);
            return RawExtensions.Contains(extension) || ImageExtensions.Contains(extension);
        }

        public static string GetDisplayType(string path)
        {
            string extension = Path.GetExtension(path);
            if (String.IsNullOrEmpty(extension))
            {
                return "未知";
            }

            if (RawExtensions.Contains(extension))
            {
                return extension.Substring(1).ToUpperInvariant() + " · RAW";
            }

            return extension.Substring(1).ToUpperInvariant();
        }

        public static IList<string> FindSupportedFiles(string folder)
        {
            List<string> files = new List<string>();
            Stack<string> pending = new Stack<string>();
            pending.Push(folder);

            while (pending.Count > 0)
            {
                string current = pending.Pop();
                try
                {
                    foreach (string file in Directory.EnumerateFiles(current))
                    {
                        if (IsSupported(file))
                        {
                            files.Add(file);
                        }
                    }

                    foreach (string directory in Directory.EnumerateDirectories(current))
                    {
                        try
                        {
                            FileAttributes attributes = File.GetAttributes(directory);
                            if ((attributes & FileAttributes.ReparsePoint) == 0)
                            {
                                pending.Push(directory);
                            }
                        }
                        catch
                        {
                            // A folder can disappear or become inaccessible while scanning.
                        }
                    }
                }
                catch
                {
                    // Continue with other accessible folders.
                }
            }

            files.Sort(StringComparer.CurrentCultureIgnoreCase);
            return files;
        }
    }

    public static class ConversionService
    {
        private const int MinimumJpegCandidateSize = 16 * 1024;
        private const int MaximumJpegCandidateSize = 96 * 1024 * 1024;
        private const long MaximumScanFileSize = 384L * 1024L * 1024L;

        public static ConversionSummary Convert(
            IList<string> inputFiles,
            ConversionOptions options,
            Action<ConversionProgress> progressCallback,
            CancellationToken cancellationToken)
        {
            if (inputFiles == null)
            {
                throw new ArgumentNullException("inputFiles");
            }

            if (options == null)
            {
                throw new ArgumentNullException("options");
            }

            ConversionSummary summary = new ConversionSummary();
            summary.Total = inputFiles.Count;

            for (int index = 0; index < inputFiles.Count; index++)
            {
                if (cancellationToken.IsCancellationRequested)
                {
                    summary.Cancelled = true;
                    break;
                }

                string sourcePath = inputFiles[index];
                FileConversionResult result = new FileConversionResult();
                result.SourcePath = sourcePath;

                try
                {
                    string outputPath;
                    bool skipped;
                    string resolvedOutput = ResolveOutputPath(sourcePath, options, out skipped);
                    outputPath = resolvedOutput;
                    result.OutputPath = outputPath;

                    if (skipped)
                    {
                        result.Skipped = true;
                        summary.Skipped++;
                    }
                    else
                    {
                        bool usedEmbeddedPreview;
                        BitmapSource bitmap = DecodeImage(
                            sourcePath,
                            options.AllowEmbeddedPreview,
                            out usedEmbeddedPreview);

                        bitmap = ApplyOrientation(sourcePath, bitmap);
                        bitmap = Resize(bitmap, options.MaxSize);

                        string outputDirectory = Path.GetDirectoryName(outputPath);
                        if (String.IsNullOrWhiteSpace(outputDirectory))
                        {
                            throw new IOException("无法确定输出文件夹。");
                        }

                        Directory.CreateDirectory(outputDirectory);
                        SaveJpegAtomically(bitmap, outputPath, options.JpegQuality);

                        try
                        {
                            File.SetCreationTimeUtc(outputPath, File.GetCreationTimeUtc(sourcePath));
                            File.SetLastWriteTimeUtc(outputPath, File.GetLastWriteTimeUtc(sourcePath));
                        }
                        catch
                        {
                            // Timestamp transfer is a convenience and must not fail the conversion.
                        }

                        result.Success = true;
                        result.UsedEmbeddedPreview = usedEmbeddedPreview;
                        summary.Succeeded++;
                        if (usedEmbeddedPreview)
                        {
                            summary.PreviewFallbacks++;
                        }
                    }
                }
                catch (Exception exception)
                {
                    result.Error = BuildFriendlyError(sourcePath, exception);
                    summary.Failed++;
                }

                summary.Results.Add(result);
                if (progressCallback != null)
                {
                    progressCallback(new ConversionProgress
                    {
                        Current = index + 1,
                        Total = inputFiles.Count,
                        FilePath = sourcePath,
                        Result = result
                    });
                }
            }

            return summary;
        }

        public static PreviewDecodeResult CreatePreview(
            string sourcePath,
            int maximumPreviewWidth,
            bool allowEmbeddedPreview)
        {
            bool usedEmbeddedPreview;
            BitmapSource decoded = DecodeImage(sourcePath, allowEmbeddedPreview, out usedEmbeddedPreview);
            BitmapSource oriented = ApplyOrientation(sourcePath, decoded);

            PreviewDecodeResult result = new PreviewDecodeResult();
            result.SourceWidth = oriented.PixelWidth;
            result.SourceHeight = oriented.PixelHeight;
            result.UsedEmbeddedPreview = usedEmbeddedPreview;

            BitmapSource preview = Resize(oriented, maximumPreviewWidth);
            if (preview.CanFreeze)
            {
                preview.Freeze();
            }

            result.Image = preview;
            return result;
        }

        public static byte[] ExtractLargestEmbeddedJpeg(string rawPath)
        {
            List<byte[]> candidates = GetEmbeddedJpegCandidates(rawPath, true);
            return candidates.Count == 0 ? null : candidates[0];
        }

        private static BitmapSource DecodeImage(
            string sourcePath,
            bool allowEmbeddedPreview,
            out bool usedEmbeddedPreview)
        {
            usedEmbeddedPreview = false;

            try
            {
                BitmapDecoder decoder = BitmapDecoder.Create(
                    new Uri(sourcePath, UriKind.Absolute),
                    BitmapCreateOptions.PreservePixelFormat,
                    BitmapCacheOption.OnLoad);

                if (decoder.Frames.Count == 0)
                {
                    throw new InvalidDataException("文件中没有可读取的图像帧。");
                }

                BitmapSource source = decoder.Frames[0];
                if (source.CanFreeze)
                {
                    source.Freeze();
                }

                return source;
            }
            catch (Exception decodeException)
            {
                if (!SupportedFormats.IsRaw(sourcePath) || !allowEmbeddedPreview)
                {
                    if (SupportedFormats.IsRaw(sourcePath))
                    {
                        throw new RawDecodeException(
                            "Windows 缺少此 RAW 格式的解码器，且未启用内嵌预览回退。",
                            decodeException);
                    }

                    throw;
                }

                BitmapSource embedded = TryDecodeEmbeddedPreview(sourcePath);
                if (embedded == null)
                {
                    throw new RawDecodeException(
                        "Windows 缺少此 RAW 格式的解码器，文件中也没有可用的内嵌 JPEG 预览。",
                        decodeException);
                }

                usedEmbeddedPreview = true;
                return embedded;
            }
        }

        private static BitmapSource TryDecodeEmbeddedPreview(string sourcePath)
        {
            List<byte[]> candidates = GetEmbeddedJpegCandidates(sourcePath, false);
            foreach (byte[] candidate in candidates)
            {
                try
                {
                    using (MemoryStream stream = new MemoryStream(candidate, false))
                    {
                        BitmapDecoder decoder = BitmapDecoder.Create(
                            stream,
                            BitmapCreateOptions.PreservePixelFormat,
                            BitmapCacheOption.OnLoad);

                        if (decoder.Frames.Count == 0)
                        {
                            continue;
                        }

                        BitmapSource image = decoder.Frames[0];
                        if (image.CanFreeze)
                        {
                            image.Freeze();
                        }

                        return image;
                    }
                }
                catch
                {
                    // Some compressed RAW streams contain marker-like byte sequences.
                }
            }

            return null;
        }

        private static List<byte[]> GetEmbeddedJpegCandidates(
            string sourcePath,
            bool largestOnly)
        {
            FileInfo info = new FileInfo(sourcePath);
            if (!info.Exists || info.Length <= 0 || info.Length > MaximumScanFileSize)
            {
                return new List<byte[]>();
            }

            byte[] data;
            try
            {
                data = File.ReadAllBytes(sourcePath);
            }
            catch
            {
                return new List<byte[]>();
            }

            List<int> starts = new List<int>();
            List<int> ends = new List<int>();

            for (int index = 0; index < data.Length - 2; index++)
            {
                if (data[index] == 0xFF && data[index + 1] == 0xD8 && data[index + 2] == 0xFF)
                {
                    starts.Add(index);
                }

                if (data[index] == 0xFF && data[index + 1] == 0xD9)
                {
                    ends.Add(index);
                }
            }

            if (starts.Count == 0 || ends.Count == 0)
            {
                return new List<byte[]>();
            }

            List<JpegCandidate> found = new List<JpegCandidate>();
            foreach (int start in starts)
            {
                int endIndex = ends.BinarySearch(start + 2);
                if (endIndex < 0)
                {
                    endIndex = ~endIndex;
                }

                if (endIndex < 0 || endIndex >= ends.Count)
                {
                    continue;
                }

                int end = ends[endIndex];
                int size = end + 2 - start;
                if (size >= MinimumJpegCandidateSize && size <= MaximumJpegCandidateSize)
                {
                    found.Add(new JpegCandidate { Start = start, Size = size });
                }
            }

            found = found
                .GroupBy(candidate => candidate.Start)
                .Select(group => group.First())
                .OrderByDescending(candidate => candidate.Size)
                .Take(largestOnly ? 1 : 16)
                .ToList();

            List<byte[]> result = new List<byte[]>();
            foreach (JpegCandidate candidate in found)
            {
                byte[] jpeg = new byte[candidate.Size];
                Buffer.BlockCopy(data, candidate.Start, jpeg, 0, candidate.Size);
                result.Add(jpeg);
            }

            return result;
        }

        private static BitmapSource ApplyOrientation(string sourcePath, BitmapSource source)
        {
            int orientation = ReadOrientation(sourcePath);
            if (orientation <= 1 || orientation > 8)
            {
                return source;
            }

            Transform transform = null;
            switch (orientation)
            {
                case 2:
                    transform = new ScaleTransform(-1, 1);
                    break;
                case 3:
                    transform = new RotateTransform(180);
                    break;
                case 4:
                    transform = new ScaleTransform(1, -1);
                    break;
                case 5:
                    transform = BuildTransform(90, -1, 1);
                    break;
                case 6:
                    transform = new RotateTransform(90);
                    break;
                case 7:
                    transform = BuildTransform(270, -1, 1);
                    break;
                case 8:
                    transform = new RotateTransform(270);
                    break;
            }

            if (transform == null)
            {
                return source;
            }

            BitmapSource transformed = new TransformedBitmap(source, transform);
            if (transformed.CanFreeze)
            {
                transformed.Freeze();
            }

            return transformed;
        }

        private static Transform BuildTransform(double angle, double scaleX, double scaleY)
        {
            TransformGroup group = new TransformGroup();
            group.Children.Add(new RotateTransform(angle));
            group.Children.Add(new ScaleTransform(scaleX, scaleY));
            return group;
        }

        private static int ReadOrientation(string sourcePath)
        {
            try
            {
                BitmapDecoder decoder = BitmapDecoder.Create(
                    new Uri(sourcePath, UriKind.Absolute),
                    BitmapCreateOptions.DelayCreation,
                    BitmapCacheOption.None);

                if (decoder.Frames.Count == 0)
                {
                    return 1;
                }

                BitmapMetadata metadata = decoder.Frames[0].Metadata as BitmapMetadata;
                if (metadata == null)
                {
                    return 1;
                }

                string[] queries =
                {
                    "/app1/ifd/{ushort=274}",
                    "/ifd/{ushort=274}",
                    "/app1/{ushort=274}"
                };

                foreach (string query in queries)
                {
                    try
                    {
                        object value = metadata.GetQuery(query);
                        if (value != null)
                        {
                            return System.Convert.ToInt32(value, CultureInfo.InvariantCulture);
                        }
                    }
                    catch
                    {
                        // Metadata schemas differ between camera vendors.
                    }
                }
            }
            catch
            {
                // Orientation metadata is optional.
            }

            return 1;
        }

        private static BitmapSource Resize(BitmapSource source, int maximumSize)
        {
            if (maximumSize <= 0)
            {
                return source;
            }

            double scale = Math.Min(
                (double)maximumSize / source.PixelWidth,
                (double)maximumSize / source.PixelHeight);
            if (scale >= 1.0)
            {
                return source;
            }

            TransformedBitmap resized = new TransformedBitmap(
                source,
                new ScaleTransform(scale, scale));
            if (resized.CanFreeze)
            {
                resized.Freeze();
            }

            return resized;
        }

        private static string ResolveOutputPath(
            string sourcePath,
            ConversionOptions options,
            out bool skipped)
        {
            skipped = false;
            string outputDirectory;
            if (options.SaveBesideOriginals)
            {
                outputDirectory = Path.Combine(
                    Path.GetDirectoryName(sourcePath),
                    "JPG");
            }
            else
            {
                outputDirectory = options.OutputDirectory;
            }

            if (String.IsNullOrWhiteSpace(outputDirectory))
            {
                throw new InvalidOperationException("请选择输出文件夹。");
            }

            string stem = Path.GetFileNameWithoutExtension(sourcePath);
            string candidate = Path.Combine(outputDirectory, stem + ".jpg");
            int suffix = 2;

            while (File.Exists(candidate))
            {
                if (options.ConflictPolicy == ConflictPolicy.Skip)
                {
                    skipped = true;
                    return candidate;
                }

                if (options.ConflictPolicy == ConflictPolicy.Overwrite)
                {
                    return candidate;
                }

                candidate = Path.Combine(
                    outputDirectory,
                    String.Format(CultureInfo.InvariantCulture, "{0} ({1}).jpg", stem, suffix));
                suffix++;
            }

            return candidate;
        }

        private static void SaveJpegAtomically(
            BitmapSource bitmap,
            string outputPath,
            int quality)
        {
            string temporaryPath = outputPath + ".tmp-" + Guid.NewGuid().ToString("N");
            try
            {
                JpegBitmapEncoder encoder = new JpegBitmapEncoder();
                encoder.QualityLevel = Math.Max(1, Math.Min(100, quality));
                encoder.Frames.Add(BitmapFrame.Create(bitmap));

                using (FileStream stream = new FileStream(
                    temporaryPath,
                    FileMode.CreateNew,
                    FileAccess.Write,
                    FileShare.None))
                {
                    encoder.Save(stream);
                }

                if (File.Exists(outputPath))
                {
                    File.Delete(outputPath);
                }

                File.Move(temporaryPath, outputPath);
            }
            finally
            {
                if (File.Exists(temporaryPath))
                {
                    try
                    {
                        File.Delete(temporaryPath);
                    }
                    catch
                    {
                    }
                }
            }
        }

        private static string BuildFriendlyError(string sourcePath, Exception exception)
        {
            Exception root = exception;
            while (root.InnerException != null)
            {
                root = root.InnerException;
            }

            if (exception is RawDecodeException)
            {
                return exception.Message;
            }

            if (root is UnauthorizedAccessException)
            {
                return "没有读取或写入权限。请换一个输出文件夹，或以管理员身份运行。";
            }

            if (root is IOException)
            {
                return "文件读写失败：" + root.Message;
            }

            string file = Path.GetFileName(sourcePath);
            return String.Format(
                CultureInfo.CurrentCulture,
                "无法转换 {0}：{1}",
                file,
                root.Message);
        }

        private sealed class JpegCandidate
        {
            public int Start { get; set; }
            public int Size { get; set; }
        }
    }
}
