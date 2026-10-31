using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Threading;
using Raw2JpgStudio;

internal static class ConversionCoreTests
{
    private static int passed;
    private static int failed;

    private static int Main()
    {
        string root = Path.Combine(
            Path.GetTempPath(),
            "Raw2JpgStudioTests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);

        try
        {
            Run("普通图片批量转 JPG 并缩放", delegate { TestStandardConversion(root); });
            Run("同目录重名时自动追加编号", delegate { TestConflictRename(root); });
            Run("同名冲突时可跳过", delegate { TestConflictSkip(root); });
            Run("RAW 解码失败时提取最大内嵌 JPEG", delegate { TestEmbeddedJpegFallback(root); });
            Run("禁用回退时 RAW 失败会给出明确错误", delegate { TestEmbeddedFallbackDisabled(root); });
            Run("递归查找支持的图像格式", delegate { TestFolderScan(root); });
        }
        finally
        {
            try
            {
                Directory.Delete(root, true);
            }
            catch
            {
            }
        }

        Console.WriteLine();
        Console.WriteLine("结果：{0} 通过，{1} 失败", passed, failed);
        return failed == 0 ? 0 : 1;
    }

    private static void TestStandardConversion(string root)
    {
        string inputDirectory = Path.Combine(root, "standard");
        string outputDirectory = Path.Combine(root, "standard-output");
        Directory.CreateDirectory(inputDirectory);
        string source = Path.Combine(inputDirectory, "sample.png");
        CreateGradientJpegOrPng(source, 1600, 900, ImageFormat.Png);

        ConversionSummary summary = ConversionService.Convert(
            new string[] { source },
            new ConversionOptions
            {
                OutputDirectory = outputDirectory,
                SaveBesideOriginals = false,
                JpegQuality = 88,
                MaxSize = 800,
                AllowEmbeddedPreview = true,
                ConflictPolicy = ConflictPolicy.Rename
            },
            null,
            CancellationToken.None);

        Assert(summary.Succeeded == 1 && summary.Failed == 0, "应成功转换 1 个文件");
        string output = summary.Results[0].OutputPath;
        Assert(File.Exists(output), "应生成输出 JPG");
        using (Image image = Image.FromFile(output))
        {
            Assert(image.Width == 800, "最长边应缩放到 800");
            Assert(image.Height == 450, "长宽比应保持为 16:9");
        }
    }

    private static void TestConflictRename(string root)
    {
        string input = Path.Combine(root, "rename-input.JPG");
        string outputDirectory = Path.Combine(root, "rename-output");
        CreateGradientJpegOrPng(input, 640, 360, ImageFormat.Jpeg);
        Directory.CreateDirectory(outputDirectory);
        File.WriteAllText(Path.Combine(outputDirectory, "rename-input.jpg"), "existing");

        ConversionSummary summary = ConversionService.Convert(
            new string[] { input },
            new ConversionOptions
            {
                OutputDirectory = outputDirectory,
                JpegQuality = 85,
                AllowEmbeddedPreview = true,
                ConflictPolicy = ConflictPolicy.Rename
            },
            null,
            CancellationToken.None);

        Assert(summary.Succeeded == 1, "重名时仍应成功生成新文件");
        Assert(Path.GetFileName(summary.Results[0].OutputPath) == "rename-input (2).jpg",
            "输出文件名应自动追加编号");
        Assert(File.Exists(summary.Results[0].OutputPath), "编号文件应存在");
    }

    private static void TestConflictSkip(string root)
    {
        string input = Path.Combine(root, "skip-input.jpg");
        string outputDirectory = Path.Combine(root, "skip-output");
        CreateGradientJpegOrPng(input, 640, 360, ImageFormat.Jpeg);
        Directory.CreateDirectory(outputDirectory);
        File.WriteAllText(Path.Combine(outputDirectory, "skip-input.jpg"), "existing");

        ConversionSummary summary = ConversionService.Convert(
            new string[] { input },
            new ConversionOptions
            {
                OutputDirectory = outputDirectory,
                ConflictPolicy = ConflictPolicy.Skip
            },
            null,
            CancellationToken.None);

        Assert(summary.Skipped == 1 && summary.Succeeded == 0, "已存在文件应被跳过");
        Assert(File.ReadAllText(summary.Results[0].OutputPath) == "existing",
            "跳过时不得改动已有文件");
    }

    private static void TestEmbeddedJpegFallback(string root)
    {
        string input = Path.Combine(root, "camera-sample.ARW");
        string outputDirectory = Path.Combine(root, "raw-output");
        CreateFakeRawWithEmbeddedJpeg(input, 1600, 900);

        ConversionSummary summary = ConversionService.Convert(
            new string[] { input },
            new ConversionOptions
            {
                OutputDirectory = outputDirectory,
                JpegQuality = 90,
                MaxSize = 0,
                AllowEmbeddedPreview = true,
                ConflictPolicy = ConflictPolicy.Rename
            },
            null,
            CancellationToken.None);

        Assert(summary.Succeeded == 1, "应通过内嵌 JPEG 完成转换");
        Assert(summary.PreviewFallbacks == 1, "结果应标记为使用内嵌预览");
        using (Image image = Image.FromFile(summary.Results[0].OutputPath))
        {
            Assert(image.Width == 1600 && image.Height == 900, "应提取到最大内嵌预览");
        }
    }

    private static void TestEmbeddedFallbackDisabled(string root)
    {
        string input = Path.Combine(root, "camera-disabled.arw");
        CreateFakeRawWithEmbeddedJpeg(input, 900, 600);

        ConversionSummary summary = ConversionService.Convert(
            new string[] { input },
            new ConversionOptions
            {
                OutputDirectory = Path.Combine(root, "raw-disabled-output"),
                AllowEmbeddedPreview = false,
                ConflictPolicy = ConflictPolicy.Rename
            },
            null,
            CancellationToken.None);

        Assert(summary.Failed == 1, "禁用回退时假 RAW 应失败");
        Assert(summary.Results[0].Error.Contains("RAW"),
            "错误信息应说明 RAW 解码器问题");
    }

    private static void TestFolderScan(string root)
    {
        string folder = Path.Combine(root, "scan", "nested");
        Directory.CreateDirectory(folder);
        File.WriteAllBytes(Path.Combine(root, "scan", "one.arw"), new byte[] { 1, 2, 3 });
        File.WriteAllBytes(Path.Combine(root, "scan", "ignore.txt"), new byte[] { 1, 2, 3 });
        File.WriteAllBytes(Path.Combine(folder, "two.JPEG"), new byte[] { 1, 2, 3 });
        File.WriteAllBytes(Path.Combine(folder, "three.dng"), new byte[] { 1, 2, 3 });

        IList<string> files = SupportedFormats.FindSupportedFiles(Path.Combine(root, "scan"));
        Assert(files.Count == 3, "应递归找到 3 个支持文件");
        Assert(!files.Contains(Path.Combine(root, "scan", "ignore.txt")), "不应包含文本文件");
    }

    private static void CreateFakeRawWithEmbeddedJpeg(
        string path,
        int width,
        int height)
    {
        byte[] jpeg;
        using (Bitmap bitmap = CreateGradientBitmap(width, height))
        using (MemoryStream stream = new MemoryStream())
        {
            bitmap.Save(stream, ImageFormat.Jpeg);
            jpeg = stream.ToArray();
        }

        if (jpeg.Length < 20 * 1024)
        {
            width = 2200;
            height = 1400;
            using (Bitmap bitmap = CreateGradientBitmap(width, height))
            using (MemoryStream stream = new MemoryStream())
            {
                bitmap.Save(stream, ImageFormat.Jpeg);
                jpeg = stream.ToArray();
            }
        }

        using (FileStream stream = new FileStream(path, FileMode.Create, FileAccess.Write))
        {
            byte[] header = new byte[4096];
            for (int index = 0; index < header.Length; index++)
            {
                header[index] = (byte)(index % 251);
            }
            stream.Write(header, 0, header.Length);
            stream.Write(jpeg, 0, jpeg.Length);
            byte[] footer = new byte[2048];
            for (int index = 0; index < footer.Length; index++)
            {
                footer[index] = (byte)((index * 7) % 251);
            }
            stream.Write(footer, 0, footer.Length);
        }
    }

    private static void CreateGradientJpegOrPng(
        string path,
        int width,
        int height,
        ImageFormat format)
    {
        using (Bitmap bitmap = CreateGradientBitmap(width, height))
        {
            bitmap.Save(path, format);
        }
    }

    private static Bitmap CreateGradientBitmap(int width, int height)
    {
        Bitmap bitmap = new Bitmap(width, height, PixelFormat.Format24bppRgb);
        using (Graphics graphics = Graphics.FromImage(bitmap))
        using (LinearGradientBrush background = new LinearGradientBrush(
            new Rectangle(0, 0, width, height),
            Color.FromArgb(22, 58, 94),
            Color.FromArgb(232, 148, 74),
            22F))
        {
            graphics.SmoothingMode = SmoothingMode.HighQuality;
            graphics.FillRectangle(background, 0, 0, width, height);

            using (SolidBrush sun = new SolidBrush(Color.FromArgb(255, 229, 171)))
            {
                graphics.FillEllipse(sun, width * 0.67F, height * 0.18F, width * 0.16F, height * 0.28F);
            }

            using (SolidBrush ridge = new SolidBrush(Color.FromArgb(26, 35, 48)))
            {
                PointF[] points =
                {
                    new PointF(0, height * 0.82F),
                    new PointF(width * 0.18F, height * 0.58F),
                    new PointF(width * 0.36F, height * 0.78F),
                    new PointF(width * 0.55F, height * 0.49F),
                    new PointF(width * 0.76F, height * 0.76F),
                    new PointF(width, height * 0.55F),
                    new PointF(width, height),
                    new PointF(0, height)
                };
                graphics.FillPolygon(ridge, points);
            }

            using (Font font = new Font("Segoe UI", Math.Max(16, width / 32.0F), FontStyle.Bold))
            using (SolidBrush textBrush = new SolidBrush(Color.White))
            {
                graphics.DrawString("RAW2JPG", font, textBrush, width * 0.05F, height * 0.06F);
            }
        }
        return bitmap;
    }

    private static void Run(string name, Action test)
    {
        try
        {
            test();
            passed++;
            Console.WriteLine("[PASS] " + name);
        }
        catch (Exception exception)
        {
            failed++;
            Console.WriteLine("[FAIL] " + name);
            Console.WriteLine("       " + exception.Message);
        }
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
