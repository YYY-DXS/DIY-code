using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Windows.Media.Imaging;

namespace Raw2JpgStudio
{
    internal static class Program
    {
        [STAThread]
        private static void Main(string[] commandLineArgs)
        {
            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.ThreadException += delegate(object sender, ThreadExceptionEventArgs args)
                {
                    WriteStartupError(args.Exception);
                    MessageBox.Show(
                        "程序遇到未处理的错误：\r\n\r\n" + args.Exception.Message,
                        "RAW 转 JPG",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error);
                };

                Application.Run(new MainForm(commandLineArgs));
            }
            catch (Exception exception)
            {
                WriteStartupError(exception);
                MessageBox.Show(
                    "程序启动失败：\r\n\r\n" + exception.Message,
                    "RAW 转 JPG",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
            }
        }

        private static void WriteStartupError(Exception exception)
        {
            try
            {
                string detail;
                try
                {
                    detail = exception.ToString();
                }
                catch
                {
                    detail =
                        exception.GetType().FullName +
                        "\r\n" +
                        exception.Message +
                        "\r\n" +
                        exception.StackTrace;
                }

                File.WriteAllText(
                    Path.Combine(Path.GetTempPath(), "Raw2JpgStudio-error.log"),
                    detail);
            }
            catch
            {
            }
        }
    }

    internal sealed class MainForm : Form
    {
        private static readonly Color CanvasColor = Color.FromArgb(246, 247, 251);
        private static readonly Color CardColor = Color.White;
        private static readonly Color InkColor = Color.FromArgb(28, 39, 57);
        private static readonly Color MutedColor = Color.FromArgb(101, 112, 133);
        private static readonly Color BorderColor = Color.FromArgb(226, 230, 237);
        private static readonly Color AccentColor = Color.FromArgb(31, 111, 235);
        private static readonly Color AccentHoverColor = Color.FromArgb(23, 92, 203);
        private static readonly Color SuccessColor = Color.FromArgb(18, 122, 90);
        private static readonly Color ErrorColor = Color.FromArgb(190, 55, 55);
        private static readonly Color WarningColor = Color.FromArgb(173, 104, 24);

        private readonly List<ImageJob> jobs = new List<ImageJob>();
        private readonly Font uiFont;
        private readonly Font uiFontBold;
        private readonly Font titleFont;

        private ListView fileList;
        private SplitContainer contentSplit;
        private Label fileCountLabel;
        private Label emptyHintLabel;
        private PictureBox previewBox;
        private Label previewPlaceholder;
        private Label previewNameLabel;
        private Label previewMetaLabel;
        private Label previewPathLabel;
        private RadioButton besideRadio;
        private RadioButton customOutputRadio;
        private TextBox outputPathBox;
        private Button browseOutputButton;
        private TrackBar qualityTrack;
        private Label qualityValueLabel;
        private ComboBox maxSizeCombo;
        private ComboBox conflictCombo;
        private CheckBox embeddedPreviewCheck;
        private CheckBox openWhenDoneCheck;
        private Label statusLabel;
        private ProgressBar progressBar;
        private Button cancelButton;
        private Button convertButton;
        private FlowLayoutPanel toolbarFlow;
        private int previewRequestId;
        private bool busy;
        private CancellationTokenSource cancellationSource;
        private readonly string[] pendingInitialPaths;

        public MainForm(string[] initialPaths)
        {
            pendingInitialPaths = initialPaths ?? new string[0];
            uiFont = new Font("Microsoft YaHei UI", 9.5F, FontStyle.Regular);
            uiFontBold = new Font("Microsoft YaHei UI", 9.5F, FontStyle.Bold);
            titleFont = new Font("Microsoft YaHei UI", 17F, FontStyle.Bold);

            InitializeWindow();
            BuildInterface();
            LoadSettings();
            UpdateOutputControls();
            UpdateFileCount();

            FormClosing += OnFormClosing;
            KeyPreview = true;
            KeyDown += OnKeyDown;
            AllowDrop = true;
            DragEnter += OnDragEnter;
            DragDrop += OnDragDrop;
        }

        private void InitializeWindow()
        {
            Text = "RAW 转 JPG · 本地批量图片转换";
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(1160, 790);
            MinimumSize = new Size(980, 700);
            BackColor = CanvasColor;
            Font = uiFont;
            AutoScaleMode = AutoScaleMode.Dpi;

            try
            {
                Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            }
            catch
            {
            }
        }

        private void BuildInterface()
        {
            TableLayoutPanel root = new TableLayoutPanel();
            root.Dock = DockStyle.Fill;
            root.ColumnCount = 1;
            root.RowCount = 5;
            root.Padding = new Padding(18, 0, 18, 16);
            root.BackColor = CanvasColor;
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, 88F));
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, 53F));
            root.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, 190F));
            root.RowStyles.Add(new RowStyle(SizeType.Absolute, 72F));
            Controls.Add(root);

            root.Controls.Add(BuildHeader(), 0, 0);
            root.Controls.Add(BuildToolbar(), 0, 1);
            root.Controls.Add(BuildContent(), 0, 2);
            root.Controls.Add(BuildSettings(), 0, 3);
            root.Controls.Add(BuildFooter(), 0, 4);
        }

        private Control BuildHeader()
        {
            Panel header = new Panel();
            header.Dock = DockStyle.Fill;
            header.Margin = new Padding(0, 18, 0, 10);
            header.BackColor = Color.FromArgb(28, 39, 57);
            header.Padding = new Padding(24, 13, 20, 12);

            TableLayoutPanel layout = new TableLayoutPanel();
            layout.Dock = DockStyle.Fill;
            layout.ColumnCount = 2;
            layout.RowCount = 1;
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 255F));
            header.Controls.Add(layout);

            Panel titlePanel = new Panel();
            titlePanel.Dock = DockStyle.Fill;
            titlePanel.BackColor = Color.Transparent;
            layout.Controls.Add(titlePanel, 0, 0);

            Label title = new Label();
            title.AutoSize = true;
            title.Text = "RAW 转 JPG";
            title.Font = titleFont;
            title.ForeColor = Color.White;
            title.Location = new Point(0, 1);
            titlePanel.Controls.Add(title);

            Label subtitle = new Label();
            subtitle.AutoSize = true;
            subtitle.Text = "把相机原始照片批量转换为通用 JPEG，全部在本机完成";
            subtitle.Font = new Font("Microsoft YaHei UI", 9F);
            subtitle.ForeColor = Color.FromArgb(188, 201, 222);
            subtitle.Location = new Point(1, 35);
            titlePanel.Controls.Add(subtitle);

            FlowLayoutPanel right = new FlowLayoutPanel();
            right.Dock = DockStyle.Fill;
            right.FlowDirection = FlowDirection.TopDown;
            right.WrapContents = false;
            right.Padding = new Padding(0);
            right.BackColor = Color.Transparent;
            layout.Controls.Add(right, 1, 0);

            Label privacy = new Label();
            privacy.AutoSize = true;
            privacy.Text = "●  本地处理 · 照片不会上传";
            privacy.Font = new Font("Microsoft YaHei UI", 8.8F, FontStyle.Bold);
            privacy.ForeColor = Color.FromArgb(111, 226, 184);
            privacy.Margin = new Padding(0);
            right.Controls.Add(privacy);

            LinkLabel rawHelp = new LinkLabel();
            rawHelp.AutoSize = true;
            rawHelp.Text = "缺少相机 RAW 解码器？";
            rawHelp.LinkColor = Color.FromArgb(180, 205, 255);
            rawHelp.ActiveLinkColor = Color.White;
            rawHelp.VisitedLinkColor = Color.FromArgb(180, 205, 255);
            rawHelp.LinkBehavior = LinkBehavior.HoverUnderline;
            rawHelp.Font = new Font("Microsoft YaHei UI", 8.5F);
            rawHelp.Margin = new Padding(0, 2, 0, 0);
            rawHelp.LinkClicked += delegate
            {
                OpenRawImageExtensionPage();
            };
            right.Controls.Add(rawHelp);

            return header;
        }

        private Control BuildToolbar()
        {
            TableLayoutPanel toolbar = new TableLayoutPanel();
            toolbar.Dock = DockStyle.Fill;
            toolbar.Margin = new Padding(0, 0, 0, 9);
            toolbar.ColumnCount = 2;
            toolbar.RowCount = 1;
            toolbar.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
            toolbar.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 220F));
            toolbar.BackColor = Color.Transparent;

            toolbarFlow = new FlowLayoutPanel();
            toolbarFlow.Dock = DockStyle.Fill;
            toolbarFlow.WrapContents = false;
            toolbarFlow.FlowDirection = FlowDirection.LeftToRight;
            toolbarFlow.Padding = new Padding(0, 2, 0, 0);
            toolbarFlow.BackColor = Color.Transparent;
            toolbar.Controls.Add(toolbarFlow, 0, 0);

            Button addFilesButton = CreateSecondaryButton("+  添加文件");
            addFilesButton.Click += delegate { ChooseFiles(); };
            toolbarFlow.Controls.Add(addFilesButton);

            Button addFolderButton = CreateSecondaryButton("+  添加文件夹");
            addFolderButton.Click += delegate { ChooseFolder(); };
            toolbarFlow.Controls.Add(addFolderButton);

            Button removeButton = CreateSecondaryButton("移除选中");
            removeButton.Click += delegate { RemoveSelected(); };
            toolbarFlow.Controls.Add(removeButton);

            Button clearButton = CreateSecondaryButton("清空列表");
            clearButton.Click += delegate { ClearJobs(); };
            toolbarFlow.Controls.Add(clearButton);

            fileCountLabel = new Label();
            fileCountLabel.Dock = DockStyle.Fill;
            fileCountLabel.TextAlign = ContentAlignment.MiddleRight;
            fileCountLabel.ForeColor = MutedColor;
            fileCountLabel.Font = uiFont;
            toolbar.Controls.Add(fileCountLabel, 1, 0);

            return toolbar;
        }

        private Control BuildContent()
        {
            contentSplit = new SplitContainer();
            contentSplit.Dock = DockStyle.Fill;
            contentSplit.Margin = new Padding(0, 0, 0, 12);
            contentSplit.BackColor = CanvasColor;
            contentSplit.SplitterWidth = 12;
            contentSplit.IsSplitterFixed = false;

            contentSplit.Panel1.Controls.Add(BuildFileCard());
            contentSplit.Panel2.Controls.Add(BuildPreviewCard());
            return contentSplit;
        }

        private Control BuildFileCard()
        {
            Panel card = CreateCard();
            card.Padding = new Padding(1);

            TableLayoutPanel layout = new TableLayoutPanel();
            layout.Dock = DockStyle.Fill;
            layout.ColumnCount = 1;
            layout.RowCount = 1;
            card.Controls.Add(layout);

            Panel listHost = new Panel();
            listHost.Dock = DockStyle.Fill;
            listHost.BackColor = CardColor;
            layout.Controls.Add(listHost, 0, 0);

            fileList = new ListView();
            fileList.Dock = DockStyle.Fill;
            fileList.View = View.Details;
            fileList.FullRowSelect = true;
            fileList.HideSelection = false;
            fileList.GridLines = false;
            fileList.BorderStyle = BorderStyle.None;
            fileList.CheckBoxes = true;
            fileList.MultiSelect = true;
            fileList.ShowItemToolTips = true;
            fileList.Font = uiFont;
            fileList.BackColor = CardColor;
            fileList.ForeColor = InkColor;
            fileList.Columns.Add("文件名", 360, HorizontalAlignment.Left);
            fileList.Columns.Add("格式", 110, HorizontalAlignment.Left);
            fileList.Columns.Add("大小", 95, HorizontalAlignment.Right);
            fileList.Columns.Add("状态", 150, HorizontalAlignment.Left);
            fileList.SelectedIndexChanged += delegate { BeginPreviewSelectedItem(); };
            fileList.ItemChecked += delegate { UpdateFileCount(); };
            fileList.MouseDoubleClick += delegate { OpenSelectedSource(); };
            fileList.AllowDrop = true;
            fileList.DragEnter += OnDragEnter;
            fileList.DragDrop += OnDragDrop;
            listHost.Controls.Add(fileList);

            emptyHintLabel = new Label();
            emptyHintLabel.Dock = DockStyle.Fill;
            emptyHintLabel.TextAlign = ContentAlignment.MiddleCenter;
            emptyHintLabel.Text = "把 RAW 照片或文件夹拖到这里\r\n也可以点击上方「添加文件 / 添加文件夹」";
            emptyHintLabel.ForeColor = Color.FromArgb(143, 152, 168);
            emptyHintLabel.Font = new Font("Microsoft YaHei UI", 10.5F);
            emptyHintLabel.BackColor = CardColor;
            emptyHintLabel.Cursor = Cursors.Hand;
            emptyHintLabel.Click += delegate { ChooseFiles(); };
            listHost.Controls.Add(emptyHintLabel);
            emptyHintLabel.BringToFront();

            return card;
        }

        private Control BuildPreviewCard()
        {
            Panel card = CreateCard();
            card.Padding = new Padding(14);

            TableLayoutPanel layout = new TableLayoutPanel();
            layout.Dock = DockStyle.Fill;
            layout.ColumnCount = 1;
            layout.RowCount = 4;
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 32F));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 71F));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 39F));
            card.Controls.Add(layout);

            Label heading = new Label();
            heading.Text = "照片预览";
            heading.Font = uiFontBold;
            heading.ForeColor = InkColor;
            heading.Dock = DockStyle.Fill;
            layout.Controls.Add(heading, 0, 0);

            Panel imageHost = new Panel();
            imageHost.Dock = DockStyle.Fill;
            imageHost.BackColor = Color.FromArgb(239, 242, 247);
            imageHost.Margin = new Padding(0, 0, 0, 10);
            layout.Controls.Add(imageHost, 0, 1);

            previewBox = new PictureBox();
            previewBox.Dock = DockStyle.Fill;
            previewBox.BackColor = Color.FromArgb(239, 242, 247);
            previewBox.SizeMode = PictureBoxSizeMode.Zoom;
            imageHost.Controls.Add(previewBox);

            previewPlaceholder = new Label();
            previewPlaceholder.Dock = DockStyle.Fill;
            previewPlaceholder.TextAlign = ContentAlignment.MiddleCenter;
            previewPlaceholder.Text = "选择一张照片查看预览";
            previewPlaceholder.ForeColor = Color.FromArgb(143, 152, 168);
            previewPlaceholder.BackColor = Color.FromArgb(239, 242, 247);
            previewPlaceholder.Font = new Font("Microsoft YaHei UI", 9.5F);
            imageHost.Controls.Add(previewPlaceholder);
            previewPlaceholder.BringToFront();

            TableLayoutPanel details = new TableLayoutPanel();
            details.Dock = DockStyle.Fill;
            details.ColumnCount = 1;
            details.RowCount = 3;
            details.RowStyles.Add(new RowStyle(SizeType.Absolute, 24F));
            details.RowStyles.Add(new RowStyle(SizeType.Absolute, 22F));
            details.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
            layout.Controls.Add(details, 0, 2);

            previewNameLabel = new Label();
            previewNameLabel.Dock = DockStyle.Fill;
            previewNameLabel.AutoEllipsis = true;
            previewNameLabel.Font = uiFontBold;
            previewNameLabel.ForeColor = InkColor;
            previewNameLabel.Text = "未选择文件";
            details.Controls.Add(previewNameLabel, 0, 0);

            previewMetaLabel = new Label();
            previewMetaLabel.Dock = DockStyle.Fill;
            previewMetaLabel.AutoEllipsis = true;
            previewMetaLabel.Font = new Font("Microsoft YaHei UI", 8.8F);
            previewMetaLabel.ForeColor = MutedColor;
            previewMetaLabel.Text = "双击列表中的文件可打开查看";
            details.Controls.Add(previewMetaLabel, 0, 1);

            previewPathLabel = new Label();
            previewPathLabel.Dock = DockStyle.Fill;
            previewPathLabel.AutoEllipsis = true;
            previewPathLabel.Font = new Font("Microsoft YaHei UI", 8.3F);
            previewPathLabel.ForeColor = Color.FromArgb(133, 143, 159);
            details.Controls.Add(previewPathLabel, 0, 2);

            Button openFolderButton = CreateSecondaryButton("打开文件所在位置");
            openFolderButton.Dock = DockStyle.Fill;
            openFolderButton.Margin = new Padding(0, 5, 0, 0);
            openFolderButton.Click += delegate { OpenSelectedSource(); };
            layout.Controls.Add(openFolderButton, 0, 3);

            return card;
        }

        private Control BuildSettings()
        {
            Panel container = CreateCard();
            container.Padding = new Padding(16, 10, 16, 10);
            container.Margin = new Padding(0, 0, 0, 10);

            TableLayoutPanel layout = new TableLayoutPanel();
            layout.Dock = DockStyle.Fill;
            layout.ColumnCount = 4;
            layout.RowCount = 5;
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 90F));
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 54F));
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 120F));
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 46F));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 31F));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 35F));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36F));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36F));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));
            container.Controls.Add(layout);

            Label heading = new Label();
            heading.Text = "导出设置";
            heading.Font = uiFontBold;
            heading.ForeColor = InkColor;
            heading.Dock = DockStyle.Fill;
            layout.SetColumnSpan(heading, 4);
            layout.Controls.Add(heading, 0, 0);

            Label destinationLabel = CreateFieldLabel("保存位置");
            layout.Controls.Add(destinationLabel, 0, 1);

            FlowLayoutPanel destinationOptions = new FlowLayoutPanel();
            destinationOptions.Dock = DockStyle.Fill;
            destinationOptions.WrapContents = false;
            destinationOptions.Margin = new Padding(0);
            layout.Controls.Add(destinationOptions, 1, 1);
            layout.SetColumnSpan(destinationOptions, 3);

            besideRadio = new RadioButton();
            besideRadio.AutoSize = true;
            besideRadio.Text = "原图旁的 JPG 文件夹";
            besideRadio.Checked = true;
            besideRadio.ForeColor = InkColor;
            besideRadio.Margin = new Padding(0, 5, 26, 0);
            besideRadio.CheckedChanged += delegate { UpdateOutputControls(); };
            destinationOptions.Controls.Add(besideRadio);

            customOutputRadio = new RadioButton();
            customOutputRadio.AutoSize = true;
            customOutputRadio.Text = "统一保存到";
            customOutputRadio.ForeColor = InkColor;
            customOutputRadio.Margin = new Padding(0, 5, 10, 0);
            customOutputRadio.CheckedChanged += delegate { UpdateOutputControls(); };
            destinationOptions.Controls.Add(customOutputRadio);

            outputPathBox = new TextBox();
            outputPathBox.Width = 340;
            outputPathBox.Margin = new Padding(0, 2, 8, 0);
            destinationOptions.Controls.Add(outputPathBox);

            browseOutputButton = CreateCompactButton("浏览");
            browseOutputButton.Click += delegate { BrowseOutputFolder(); };
            destinationOptions.Controls.Add(browseOutputButton);

            Button openOutputButton = CreateCompactButton("打开");
            openOutputButton.Click += delegate { OpenOutputFolder(); };
            destinationOptions.Controls.Add(openOutputButton);

            Label settingsLabel = CreateFieldLabel("画质与尺寸");
            layout.Controls.Add(settingsLabel, 0, 2);

            FlowLayoutPanel qualityPanel = new FlowLayoutPanel();
            qualityPanel.Dock = DockStyle.Fill;
            qualityPanel.WrapContents = false;
            qualityPanel.Margin = new Padding(0);
            layout.Controls.Add(qualityPanel, 1, 2);
            layout.SetColumnSpan(qualityPanel, 3);

            Label qualityLabel = new Label();
            qualityLabel.Text = "JPEG 质量";
            qualityLabel.AutoSize = true;
            qualityLabel.ForeColor = MutedColor;
            qualityLabel.Margin = new Padding(0, 8, 9, 0);
            qualityPanel.Controls.Add(qualityLabel);

            qualityTrack = new TrackBar();
            qualityTrack.Minimum = 60;
            qualityTrack.Maximum = 100;
            qualityTrack.Value = 92;
            qualityTrack.TickFrequency = 5;
            qualityTrack.SmallChange = 1;
            qualityTrack.LargeChange = 5;
            qualityTrack.Width = 210;
            qualityTrack.Height = 30;
            qualityTrack.Margin = new Padding(0, 0, 5, 0);
            qualityTrack.ValueChanged += delegate { UpdateQualityLabel(); };
            qualityPanel.Controls.Add(qualityTrack);

            qualityValueLabel = new Label();
            qualityValueLabel.Text = "92";
            qualityValueLabel.AutoSize = true;
            qualityValueLabel.Font = uiFontBold;
            qualityValueLabel.ForeColor = InkColor;
            qualityValueLabel.Margin = new Padding(0, 8, 27, 0);
            qualityPanel.Controls.Add(qualityValueLabel);

            Label maxSizeLabel = new Label();
            maxSizeLabel.Text = "最长边";
            maxSizeLabel.AutoSize = true;
            maxSizeLabel.ForeColor = MutedColor;
            maxSizeLabel.Margin = new Padding(0, 8, 8, 0);
            qualityPanel.Controls.Add(maxSizeLabel);

            maxSizeCombo = new ComboBox();
            maxSizeCombo.DropDownStyle = ComboBoxStyle.DropDownList;
            maxSizeCombo.Width = 152;
            maxSizeCombo.Margin = new Padding(0, 2, 0, 0);
            maxSizeCombo.Items.Add(new SizeOption("保持原尺寸", 0));
            maxSizeCombo.Items.Add(new SizeOption("最长边 3840 px", 3840));
            maxSizeCombo.Items.Add(new SizeOption("最长边 2560 px", 2560));
            maxSizeCombo.Items.Add(new SizeOption("最长边 1920 px", 1920));
            maxSizeCombo.Items.Add(new SizeOption("最长边 1280 px", 1280));
            maxSizeCombo.SelectedIndex = 0;
            qualityPanel.Controls.Add(maxSizeCombo);

            Label conflictLabel = CreateFieldLabel("文件重名时");
            layout.Controls.Add(conflictLabel, 0, 3);

            FlowLayoutPanel optionsPanel = new FlowLayoutPanel();
            optionsPanel.Dock = DockStyle.Fill;
            optionsPanel.WrapContents = false;
            optionsPanel.Margin = new Padding(0);
            layout.Controls.Add(optionsPanel, 1, 3);
            layout.SetColumnSpan(optionsPanel, 3);

            conflictCombo = new ComboBox();
            conflictCombo.DropDownStyle = ComboBoxStyle.DropDownList;
            conflictCombo.Width = 180;
            conflictCombo.Margin = new Padding(0, 2, 22, 0);
            conflictCombo.Items.Add(new ConflictOption("追加编号，保留两者", ConflictPolicy.Rename));
            conflictCombo.Items.Add(new ConflictOption("跳过已有文件", ConflictPolicy.Skip));
            conflictCombo.Items.Add(new ConflictOption("覆盖已有文件", ConflictPolicy.Overwrite));
            conflictCombo.SelectedIndex = 0;
            optionsPanel.Controls.Add(conflictCombo);

            embeddedPreviewCheck = new CheckBox();
            embeddedPreviewCheck.AutoSize = true;
            embeddedPreviewCheck.Text = "RAW 解码失败时提取内嵌预览（分辨率可能较低）";
            embeddedPreviewCheck.Checked = true;
            embeddedPreviewCheck.ForeColor = InkColor;
            embeddedPreviewCheck.Margin = new Padding(0, 5, 20, 0);
            optionsPanel.Controls.Add(embeddedPreviewCheck);

            openWhenDoneCheck = new CheckBox();
            openWhenDoneCheck.AutoSize = true;
            openWhenDoneCheck.Text = "完成后打开输出文件夹";
            openWhenDoneCheck.Checked = true;
            openWhenDoneCheck.ForeColor = InkColor;
            openWhenDoneCheck.Margin = new Padding(0, 5, 0, 0);
            optionsPanel.Controls.Add(openWhenDoneCheck);

            Label tip = new Label();
            tip.Text = "提示：选择「统一保存到」时，不同文件夹里的同名照片会自动追加编号，不会覆盖原图。";
            tip.Dock = DockStyle.Fill;
            tip.ForeColor = Color.FromArgb(130, 140, 156);
            tip.Font = new Font("Microsoft YaHei UI", 8.3F);
            tip.AutoEllipsis = true;
            layout.SetColumnSpan(tip, 4);
            layout.Controls.Add(tip, 0, 4);

            UpdateQualityLabel();
            return container;
        }

        private Control BuildFooter()
        {
            TableLayoutPanel footer = new TableLayoutPanel();
            footer.Dock = DockStyle.Fill;
            footer.ColumnCount = 4;
            footer.RowCount = 1;
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 290F));
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 92F));
            footer.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 160F));
            footer.Padding = new Padding(2, 7, 0, 0);
            footer.BackColor = Color.Transparent;

            statusLabel = new Label();
            statusLabel.Dock = DockStyle.Fill;
            statusLabel.TextAlign = ContentAlignment.MiddleLeft;
            statusLabel.ForeColor = MutedColor;
            statusLabel.Text = "就绪。可拖入照片或文件夹。";
            statusLabel.AutoEllipsis = true;
            footer.Controls.Add(statusLabel, 0, 0);

            progressBar = new ProgressBar();
            progressBar.Dock = DockStyle.Fill;
            progressBar.Margin = new Padding(0, 10, 17, 10);
            progressBar.Style = ProgressBarStyle.Continuous;
            progressBar.Maximum = 100;
            progressBar.Value = 0;
            footer.Controls.Add(progressBar, 1, 0);

            cancelButton = CreateSecondaryButton("取消");
            cancelButton.Dock = DockStyle.Fill;
            cancelButton.Enabled = false;
            cancelButton.Margin = new Padding(0, 4, 9, 4);
            cancelButton.Click += delegate { CancelConversion(); };
            footer.Controls.Add(cancelButton, 2, 0);

            convertButton = CreatePrimaryButton("开始转换");
            convertButton.Dock = DockStyle.Fill;
            convertButton.Margin = new Padding(0, 2, 0, 2);
            convertButton.Click += async delegate { await StartConversionAsync(); };
            footer.Controls.Add(convertButton, 3, 0);

            return footer;
        }

        private Panel CreateCard()
        {
            Panel card = new Panel();
            card.Dock = DockStyle.Fill;
            card.BackColor = CardColor;
            card.Paint += PaintCardBorder;
            return card;
        }

        private void PaintCardBorder(object sender, PaintEventArgs args)
        {
            Control control = (Control)sender;
            using (Pen pen = new Pen(BorderColor))
            {
                args.Graphics.DrawRectangle(
                    pen,
                    0,
                    0,
                    Math.Max(0, control.ClientSize.Width - 1),
                    Math.Max(0, control.ClientSize.Height - 1));
            }
        }

        private Label CreateFieldLabel(string text)
        {
            Label label = new Label();
            label.Text = text;
            label.Dock = DockStyle.Fill;
            label.TextAlign = ContentAlignment.MiddleLeft;
            label.ForeColor = MutedColor;
            return label;
        }

        private Button CreatePrimaryButton(string text)
        {
            Button button = new Button();
            button.Text = text;
            button.Font = new Font("Microsoft YaHei UI", 10.5F, FontStyle.Bold);
            button.ForeColor = Color.White;
            button.BackColor = AccentColor;
            button.FlatStyle = FlatStyle.Flat;
            button.FlatAppearance.BorderSize = 0;
            button.FlatAppearance.MouseOverBackColor = AccentHoverColor;
            button.FlatAppearance.MouseDownBackColor = Color.FromArgb(18, 80, 181);
            button.Cursor = Cursors.Hand;
            button.UseVisualStyleBackColor = false;
            return button;
        }

        private Button CreateSecondaryButton(string text)
        {
            Button button = new Button();
            button.Text = text;
            button.Font = uiFont;
            button.ForeColor = InkColor;
            button.BackColor = Color.White;
            button.FlatStyle = FlatStyle.Flat;
            button.FlatAppearance.BorderColor = BorderColor;
            button.FlatAppearance.BorderSize = 1;
            button.FlatAppearance.MouseOverBackColor = Color.FromArgb(247, 249, 252);
            button.FlatAppearance.MouseDownBackColor = Color.FromArgb(239, 243, 249);
            button.Cursor = Cursors.Hand;
            button.UseVisualStyleBackColor = false;
            button.Size = new Size(104, 34);
            button.Margin = new Padding(0, 0, 8, 0);
            return button;
        }

        private Button CreateCompactButton(string text)
        {
            Button button = CreateSecondaryButton(text);
            button.AutoSize = false;
            button.Size = new Size(58, 29);
            button.Margin = new Padding(0, 2, 6, 0);
            button.Padding = new Padding(0);
            return button;
        }

        private void ChooseFiles()
        {
            if (busy)
            {
                return;
            }

            using (OpenFileDialog dialog = new OpenFileDialog())
            {
                dialog.Title = "选择 RAW 照片或普通图片";
                dialog.Multiselect = true;
                dialog.Filter =
                    "支持的图片|*.arw;*.cr2;*.cr3;*.nef;*.nrw;*.raf;*.orf;*.rw2;*.dng;*.pef;*.srw;*.raw;*.x3f;*.jpg;*.jpeg;*.png;*.tif;*.tiff;*.bmp;*.webp;*.gif|" +
                    "RAW 原始照片|*.arw;*.cr2;*.cr3;*.crw;*.nef;*.nrw;*.raf;*.orf;*.rw2;*.dng;*.pef;*.srw;*.raw;*.x3f;*.3fr;*.erf;*.mef;*.mos;*.mrw;*.rwl|" +
                    "所有文件|*.*";
                if (dialog.ShowDialog(this) == DialogResult.OK)
                {
                    AddPaths(dialog.FileNames);
                }
            }
        }

        private void ChooseFolder()
        {
            if (busy)
            {
                return;
            }

            using (FolderBrowserDialog dialog = new FolderBrowserDialog())
            {
                dialog.Description = "选择包含 RAW 照片的文件夹（会包含子文件夹）";
                dialog.ShowNewFolderButton = false;
                if (dialog.ShowDialog(this) == DialogResult.OK)
                {
                    AddPaths(new string[] { dialog.SelectedPath });
                }
            }
        }

        private void AddPaths(IEnumerable<string> paths)
        {
            if (paths == null)
            {
                return;
            }

            Cursor previousCursor = Cursor;
            Cursor = Cursors.WaitCursor;
            int added = 0;
            int ignored = 0;
            HashSet<string> existing = new HashSet<string>(
                jobs.Select(job => job.Path),
                StringComparer.OrdinalIgnoreCase);

            try
            {
                foreach (string path in paths)
                {
                    if (File.Exists(path))
                    {
                        added += AddSingleFile(path, existing, ref ignored);
                    }
                    else if (Directory.Exists(path))
                    {
                        foreach (string file in SupportedFormats.FindSupportedFiles(path))
                        {
                            added += AddSingleFile(file, existing, ref ignored);
                        }
                    }
                    else
                    {
                        ignored++;
                    }
                }
            }
            finally
            {
                Cursor = previousCursor;
            }

            jobs.Sort(delegate(ImageJob left, ImageJob right)
            {
                return StringComparer.CurrentCultureIgnoreCase.Compare(left.Path, right.Path);
            });

            RefreshFileList();
            UpdateFileCount();

            if (added > 0)
            {
                statusLabel.ForeColor = SuccessColor;
                statusLabel.Text = String.Format(
                    "已添加 {0} 个文件。可直接拖放更多文件，或开始转换。",
                    added);
            }
            else if (ignored > 0)
            {
                statusLabel.ForeColor = WarningColor;
                statusLabel.Text = "没有添加新文件：文件格式不受支持，或已经在列表中。";
            }

            if (fileList.Items.Count > 0 && fileList.SelectedItems.Count == 0)
            {
                fileList.Items[0].Selected = true;
                fileList.Select();
            }
        }

        private int AddSingleFile(
            string path,
            HashSet<string> existing,
            ref int ignored)
        {
            if (!SupportedFormats.IsSupported(path) || existing.Contains(path))
            {
                ignored++;
                return 0;
            }

            FileInfo info = new FileInfo(path);
            if (!info.Exists)
            {
                ignored++;
                return 0;
            }

            jobs.Add(new ImageJob
            {
                Path = info.FullName,
                Size = info.Length
            });
            existing.Add(info.FullName);
            return 1;
        }

        private void RefreshFileList()
        {
            string selectedPath = null;
            if (fileList.SelectedItems.Count > 0)
            {
                selectedPath = ((ImageJob)fileList.SelectedItems[0].Tag).Path;
            }

            fileList.BeginUpdate();
            fileList.Items.Clear();
            foreach (ImageJob job in jobs)
            {
                ListViewItem item = new ListViewItem(Path.GetFileName(job.Path));
                item.SubItems.Add(SupportedFormats.GetDisplayType(job.Path));
                item.SubItems.Add(FormatFileSize(job.Size));
                item.SubItems.Add(job.Status);
                item.Tag = job;
                item.Checked = true;
                item.ForeColor = InkColor;
                fileList.Items.Add(item);

                if (selectedPath != null &&
                    String.Equals(selectedPath, job.Path, StringComparison.OrdinalIgnoreCase))
                {
                    item.Selected = true;
                }
            }
            fileList.EndUpdate();

            emptyHintLabel.Visible = jobs.Count == 0;
            if (jobs.Count > 0)
            {
                emptyHintLabel.SendToBack();
            }
            else
            {
                ClearPreview();
            }
        }

        private void RemoveSelected()
        {
            if (busy || fileList.SelectedItems.Count == 0)
            {
                return;
            }

            HashSet<string> selectedPaths = new HashSet<string>(
                fileList.SelectedItems
                    .Cast<ListViewItem>()
                    .Select(item => ((ImageJob)item.Tag).Path),
                StringComparer.OrdinalIgnoreCase);

            jobs.RemoveAll(job => selectedPaths.Contains(job.Path));
            RefreshFileList();
            UpdateFileCount();
            ClearPreview();
            statusLabel.ForeColor = MutedColor;
            statusLabel.Text = String.Format("已移除 {0} 个文件。", selectedPaths.Count);
        }

        private void ClearJobs()
        {
            if (busy || jobs.Count == 0)
            {
                return;
            }

            jobs.Clear();
            RefreshFileList();
            UpdateFileCount();
            ClearPreview();
            statusLabel.ForeColor = MutedColor;
            statusLabel.Text = "列表已清空。";
        }

        private void UpdateFileCount()
        {
            if (fileCountLabel == null)
            {
                return;
            }

            int checkedCount = fileList == null
                ? 0
                : fileList.Items.Cast<ListViewItem>().Count(item => item.Checked);
            fileCountLabel.Text = String.Format(
                "已选择 {0} / 共 {1} 个文件",
                checkedCount,
                jobs.Count);
        }

        private async void BeginPreviewSelectedItem()
        {
            int requestId = ++previewRequestId;
            if (fileList.SelectedItems.Count == 0)
            {
                ClearPreview();
                return;
            }

            ImageJob job = (ImageJob)fileList.SelectedItems[0].Tag;
            string path = job.Path;
            previewNameLabel.Text = Path.GetFileName(path);
            previewMetaLabel.Text = "正在读取预览…";
            previewPathLabel.Text = path;
            previewPlaceholder.Text = "正在读取预览…";
            previewPlaceholder.Visible = true;
            previewPlaceholder.BringToFront();

            await Task.Delay(100);
            if (requestId != previewRequestId || !File.Exists(path))
            {
                return;
            }

            try
            {
                PreviewUiResult decoded = await Task.Run(delegate
                {
                    PreviewDecodeResult preview = ConversionService.CreatePreview(path, 900, true);
                    return new PreviewUiResult
                    {
                        Bitmap = BitmapSourceToBitmap(preview.Image),
                        SourceWidth = preview.SourceWidth,
                        SourceHeight = preview.SourceHeight,
                        UsedEmbeddedPreview = preview.UsedEmbeddedPreview
                    };
                });

                if (requestId != previewRequestId || IsDisposed)
                {
                    decoded.Bitmap.Dispose();
                    return;
                }

                Image oldImage = previewBox.Image;
                previewBox.Image = decoded.Bitmap;
                if (oldImage != null)
                {
                    oldImage.Dispose();
                }

                previewPlaceholder.Visible = false;
                previewMetaLabel.Text = String.Format(
                    "{0:N0} × {1:N0} px  ·  {2}  ·  {3}",
                    decoded.SourceWidth,
                    decoded.SourceHeight,
                    FormatFileSize(job.Size),
                    decoded.UsedEmbeddedPreview ? "内嵌预览" : "完整解码");
                if (decoded.UsedEmbeddedPreview)
                {
                    previewMetaLabel.ForeColor = WarningColor;
                }
                else
                {
                    previewMetaLabel.ForeColor = MutedColor;
                }
            }
            catch (Exception exception)
            {
                if (requestId != previewRequestId)
                {
                    return;
                }

                ClearPreview();
                previewNameLabel.Text = Path.GetFileName(path);
                previewPathLabel.Text = path;
                previewPlaceholder.Text =
                    "无法生成预览\r\n\r\n" +
                    "请安装 Windows RAW Image Extension，\r\n" +
                    "或勾选内嵌预览回退后重试。";
                previewMetaLabel.ForeColor = WarningColor;
                previewMetaLabel.Text = ShortenMessage(exception.Message, 80);
            }
        }

        private static Bitmap BitmapSourceToBitmap(BitmapSource source)
        {
            PngBitmapEncoder encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(source));
            using (MemoryStream stream = new MemoryStream())
            {
                encoder.Save(stream);
                stream.Position = 0;
                using (Image image = Image.FromStream(stream))
                {
                    return new Bitmap(image);
                }
            }
        }

        private void ClearPreview()
        {
            previewRequestId++;
            Image image = previewBox == null ? null : previewBox.Image;
            if (previewBox != null)
            {
                previewBox.Image = null;
            }
            if (image != null)
            {
                image.Dispose();
            }

            if (previewPlaceholder != null)
            {
                previewPlaceholder.Text = "选择一张照片查看预览";
                previewPlaceholder.Visible = true;
                previewPlaceholder.BringToFront();
            }
            if (previewNameLabel != null)
            {
                previewNameLabel.Text = "未选择文件";
            }
            if (previewMetaLabel != null)
            {
                previewMetaLabel.Text = "双击列表中的文件可打开查看";
                previewMetaLabel.ForeColor = MutedColor;
            }
            if (previewPathLabel != null)
            {
                previewPathLabel.Text = "";
            }
        }

        private async Task StartConversionAsync()
        {
            if (busy)
            {
                return;
            }

            List<ImageJob> selectedJobs = GetCheckedJobs();
            if (selectedJobs.Count == 0)
            {
                MessageBox.Show(
                    this,
                    "请先添加文件，并勾选需要转换的照片。",
                    "没有可转换的文件",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
                return;
            }

            if (!customOutputRadio.Checked && String.IsNullOrWhiteSpace(outputPathBox.Text))
            {
                outputPathBox.Text = GetDefaultOutputDirectory();
            }

            if (customOutputRadio.Checked)
            {
                string outputDirectory = outputPathBox.Text.Trim();
                if (String.IsNullOrWhiteSpace(outputDirectory))
                {
                    MessageBox.Show(
                        this,
                        "请选择统一输出文件夹。",
                        "缺少输出位置",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Warning);
                    return;
                }

                try
                {
                    Directory.CreateDirectory(outputDirectory);
                }
                catch (Exception exception)
                {
                    MessageBox.Show(
                        this,
                        "无法创建输出文件夹：\r\n" + exception.Message,
                        "输出位置不可用",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error);
                    return;
                }
            }

            SaveSettings();
            cancellationSource = new CancellationTokenSource();
            SetBusy(true);

            foreach (ImageJob job in selectedJobs)
            {
                job.Status = "等待转换";
                SetJobStatus(job.Path, "等待转换", MutedColor, null);
            }

            ConversionOptions options = ReadConversionOptions();
            string[] inputPaths = selectedJobs.Select(job => job.Path).ToArray();
            CancellationToken token = cancellationSource.Token;
            IProgress<ConversionProgress> progress = new Progress<ConversionProgress>(
                delegate(ConversionProgress update)
                {
                    UpdateConversionProgress(update);
                });

            statusLabel.ForeColor = AccentColor;
            statusLabel.Text = String.Format("正在处理 {0} 个文件…", inputPaths.Length);
            progressBar.Value = 0;

            try
            {
                ConversionSummary summary = await Task.Run(delegate
                {
                    return ConversionService.Convert(
                        inputPaths,
                        options,
                        delegate(ConversionProgress update)
                        {
                            progress.Report(update);
                        },
                        token);
                });

                progressBar.Value = 100;
                if (summary.Cancelled)
                {
                    statusLabel.ForeColor = WarningColor;
                    statusLabel.Text = String.Format(
                        "已取消。完成 {0} 个，失败 {1} 个，跳过 {2} 个。",
                        summary.Succeeded,
                        summary.Failed,
                        summary.Skipped);
                }
                else if (summary.Failed > 0)
                {
                    statusLabel.ForeColor = ErrorColor;
                    statusLabel.Text = String.Format(
                        "转换结束：成功 {0} 个，失败 {1} 个，跳过 {2} 个。将鼠标停在失败项上可查看原因。",
                        summary.Succeeded,
                        summary.Failed,
                        summary.Skipped);
                }
                else
                {
                    statusLabel.ForeColor = SuccessColor;
                    statusLabel.Text = String.Format(
                        "转换完成：成功 {0} 个{1}，跳过 {2} 个。",
                        summary.Succeeded,
                        summary.PreviewFallbacks > 0
                            ? String.Format("（其中 {0} 个使用内嵌预览）", summary.PreviewFallbacks)
                            : "",
                        summary.Skipped);
                }

                if (openWhenDoneCheck.Checked && summary.Succeeded > 0)
                {
                    OpenCompletedOutputFolder(summary, options);
                }
            }
            catch (Exception exception)
            {
                statusLabel.ForeColor = ErrorColor;
                statusLabel.Text = "转换失败：" + ShortenMessage(exception.Message, 110);
                MessageBox.Show(
                    this,
                    "转换过程中出现错误：\r\n\r\n" + exception.Message,
                    "转换失败",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
            }
            finally
            {
                cancellationSource.Dispose();
                cancellationSource = null;
                SetBusy(false);
            }
        }

        private List<ImageJob> GetCheckedJobs()
        {
            return fileList.Items
                .Cast<ListViewItem>()
                .Where(item => item.Checked)
                .Select(item => (ImageJob)item.Tag)
                .ToList();
        }

        private ConversionOptions ReadConversionOptions()
        {
            SizeOption sizeOption = (SizeOption)maxSizeCombo.SelectedItem;
            ConflictOption conflictOption = (ConflictOption)conflictCombo.SelectedItem;
            return new ConversionOptions
            {
                SaveBesideOriginals = besideRadio.Checked,
                OutputDirectory = outputPathBox.Text.Trim(),
                JpegQuality = qualityTrack.Value,
                MaxSize = sizeOption == null ? 0 : sizeOption.Value,
                AllowEmbeddedPreview = embeddedPreviewCheck.Checked,
                ConflictPolicy = conflictOption == null
                    ? ConflictPolicy.Rename
                    : conflictOption.Value
            };
        }

        private void UpdateConversionProgress(ConversionProgress update)
        {
            if (IsDisposed)
            {
                return;
            }

            int percent = update.Total <= 0
                ? 0
                : (int)Math.Round(update.Current * 100.0 / update.Total);
            progressBar.Value = Math.Max(0, Math.Min(100, percent));

            string fileName = Path.GetFileName(update.FilePath);
            statusLabel.Text = String.Format(
                "正在处理 {0} / {1}  ·  {2}",
                update.Current,
                update.Total,
                fileName);

            FileConversionResult result = update.Result;
            ImageJob job = jobs.FirstOrDefault(
                candidate => String.Equals(
                    candidate.Path,
                    update.FilePath,
                    StringComparison.OrdinalIgnoreCase));
            if (job == null)
            {
                return;
            }

            if (result.Skipped)
            {
                job.Status = "已跳过";
                SetJobStatus(job.Path, job.Status, MutedColor, null);
            }
            else if (result.Success && result.UsedEmbeddedPreview)
            {
                job.Status = "完成 · 内嵌预览";
                SetJobStatus(
                    job.Path,
                    job.Status,
                    WarningColor,
                    "完整 RAW 解码失败，已使用文件中内嵌的 JPEG 预览。分辨率可能低于原始照片。");
            }
            else if (result.Success)
            {
                job.Status = "转换完成";
                SetJobStatus(
                    job.Path,
                    job.Status,
                    SuccessColor,
                    result.OutputPath);
            }
            else
            {
                job.Status = "失败";
                SetJobStatus(job.Path, job.Status, ErrorColor, result.Error);
            }
        }

        private void SetJobStatus(string path, string status, Color color, string tooltip)
        {
            ListViewItem item = fileList.Items
                .Cast<ListViewItem>()
                .FirstOrDefault(
                    candidate => String.Equals(
                        ((ImageJob)candidate.Tag).Path,
                        path,
                        StringComparison.OrdinalIgnoreCase));
            if (item == null)
            {
                return;
            }

            item.SubItems[3].Text = status;
            item.ForeColor = color;
            item.ToolTipText = tooltip;
        }

        private void SetBusy(bool isBusy)
        {
            busy = isBusy;
            toolbarFlow.Enabled = !isBusy;
            fileList.Enabled = !isBusy;
            besideRadio.Enabled = !isBusy;
            customOutputRadio.Enabled = !isBusy;
            outputPathBox.Enabled = !isBusy && customOutputRadio.Checked;
            browseOutputButton.Enabled = !isBusy && customOutputRadio.Checked;
            qualityTrack.Enabled = !isBusy;
            maxSizeCombo.Enabled = !isBusy;
            conflictCombo.Enabled = !isBusy;
            embeddedPreviewCheck.Enabled = !isBusy;
            openWhenDoneCheck.Enabled = !isBusy;
            convertButton.Enabled = !isBusy;
            cancelButton.Enabled = isBusy;
            UseWaitCursor = isBusy;
        }

        private void CancelConversion()
        {
            if (cancellationSource == null)
            {
                return;
            }

            cancelButton.Enabled = false;
            statusLabel.ForeColor = WarningColor;
            statusLabel.Text = "正在取消，当前照片处理完后停止…";
            cancellationSource.Cancel();
        }

        private void UpdateOutputControls()
        {
            if (besideRadio == null || customOutputRadio == null || outputPathBox == null)
            {
                return;
            }

            bool custom = customOutputRadio.Checked;
            outputPathBox.Enabled = !busy && custom;
            browseOutputButton.Enabled = !busy && custom;
            outputPathBox.BackColor = custom ? Color.White : Color.FromArgb(245, 246, 249);
        }

        private void BrowseOutputFolder()
        {
            using (FolderBrowserDialog dialog = new FolderBrowserDialog())
            {
                dialog.Description = "选择统一输出文件夹";
                dialog.ShowNewFolderButton = true;
                if (Directory.Exists(outputPathBox.Text))
                {
                    dialog.SelectedPath = outputPathBox.Text;
                }

                if (dialog.ShowDialog(this) == DialogResult.OK)
                {
                    outputPathBox.Text = dialog.SelectedPath;
                }
            }
        }

        private void OpenOutputFolder()
        {
            string folder = customOutputRadio.Checked
                ? outputPathBox.Text.Trim()
                : GetSelectedSidecarFolder();
            OpenFolder(folder, false);
        }

        private void OpenCompletedOutputFolder(
            ConversionSummary summary,
            ConversionOptions options)
        {
            if (!options.SaveBesideOriginals)
            {
                OpenFolder(options.OutputDirectory, true);
                return;
            }

            FileConversionResult first = summary.Results.FirstOrDefault(
                result => result.Success && !String.IsNullOrEmpty(result.OutputPath));
            if (first != null)
            {
                OpenFolder(Path.GetDirectoryName(first.OutputPath), true);
            }
        }

        private string GetSelectedSidecarFolder()
        {
            if (fileList.SelectedItems.Count == 0)
            {
                return "";
            }

            ImageJob job = (ImageJob)fileList.SelectedItems[0].Tag;
            return Path.Combine(Path.GetDirectoryName(job.Path), "JPG");
        }

        private void OpenSelectedSource()
        {
            if (fileList.SelectedItems.Count == 0)
            {
                return;
            }

            ImageJob job = (ImageJob)fileList.SelectedItems[0].Tag;
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = job.Path,
                    UseShellExecute = true
                });
            }
            catch (Exception exception)
            {
                MessageBox.Show(
                    this,
                    "无法打开文件：\r\n" + exception.Message,
                    "打开失败",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning);
            }
        }

        private void OpenFolder(string folder, bool createIfMissing)
        {
            if (String.IsNullOrWhiteSpace(folder))
            {
                MessageBox.Show(
                    this,
                    "请先选择照片或指定输出文件夹。",
                    "没有可打开的位置",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
                return;
            }

            try
            {
                if (createIfMissing)
                {
                    Directory.CreateDirectory(folder);
                }

                Process.Start(new ProcessStartInfo
                {
                    FileName = folder,
                    UseShellExecute = true
                });
            }
            catch (Exception exception)
            {
                MessageBox.Show(
                    this,
                    "无法打开文件夹：\r\n" + exception.Message,
                    "打开失败",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning);
            }
        }

        private void OpenRawImageExtensionPage()
        {
            try
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = "ms-windows-store://pdp/?ProductId=9NCTDW2W1BH8",
                    UseShellExecute = true
                });
            }
            catch
            {
                MessageBox.Show(
                    this,
                    "无法打开 Microsoft Store。\r\n\r\n" +
                    "请在商店搜索「Raw Image Extension」并安装，然后重新打开本程序。",
                    "安装 RAW 组件",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
            }
        }

        private void OnDragEnter(object sender, DragEventArgs args)
        {
            if (!busy && args.Data.GetDataPresent(DataFormats.FileDrop))
            {
                args.Effect = DragDropEffects.Copy;
            }
            else
            {
                args.Effect = DragDropEffects.None;
            }
        }

        private void OnDragDrop(object sender, DragEventArgs args)
        {
            if (busy || !args.Data.GetDataPresent(DataFormats.FileDrop))
            {
                return;
            }

            string[] paths = args.Data.GetData(DataFormats.FileDrop) as string[];
            AddPaths(paths);
        }

        private void OnKeyDown(object sender, KeyEventArgs args)
        {
            if (args.Control && args.KeyCode == Keys.O)
            {
                if (args.Shift)
                {
                    ChooseFolder();
                }
                else
                {
                    ChooseFiles();
                }
                args.SuppressKeyPress = true;
            }
            else if (args.KeyCode == Keys.Delete)
            {
                RemoveSelected();
                args.SuppressKeyPress = true;
            }
            else if (args.KeyCode == Keys.F5 && !busy)
            {
                Task ignored = StartConversionAsync();
                args.SuppressKeyPress = true;
            }
        }

        private void UpdateQualityLabel()
        {
            if (qualityValueLabel != null && qualityTrack != null)
            {
                qualityValueLabel.Text = qualityTrack.Value.ToString();
            }
        }

        private void LoadSettings()
        {
            string defaultOutput = GetDefaultOutputDirectory();
            outputPathBox.Text = defaultOutput;
            besideRadio.Checked = true;

            try
            {
                string settingsPath = GetSettingsPath();
                if (!File.Exists(settingsPath))
                {
                    return;
                }

                Dictionary<string, string> values = File.ReadAllLines(settingsPath)
                    .Where(line => line.Contains("="))
                    .Select(line => line.Split(new char[] { '=' }, 2))
                    .ToDictionary(parts => parts[0], parts => parts[1], StringComparer.OrdinalIgnoreCase);

                string value;
                if (values.TryGetValue("Sidecar", out value))
                {
                    besideRadio.Checked = value == "1";
                    customOutputRadio.Checked = value != "1";
                }

                if (values.TryGetValue("Output", out value) && Directory.Exists(value))
                {
                    outputPathBox.Text = value;
                }

                int integer;
                if (values.TryGetValue("Quality", out value) &&
                    Int32.TryParse(value, out integer))
                {
                    qualityTrack.Value = Math.Max(
                        qualityTrack.Minimum,
                        Math.Min(qualityTrack.Maximum, integer));
                }

                if (values.TryGetValue("MaxSize", out value) &&
                    Int32.TryParse(value, out integer))
                {
                    SelectComboValue(maxSizeCombo, integer);
                }

                if (values.TryGetValue("Conflict", out value) &&
                    Int32.TryParse(value, out integer))
                {
                    SelectComboValue(conflictCombo, integer);
                }

                if (values.TryGetValue("EmbeddedPreview", out value))
                {
                    embeddedPreviewCheck.Checked = value == "1";
                }

                if (values.TryGetValue("OpenWhenDone", out value))
                {
                    openWhenDoneCheck.Checked = value == "1";
                }
            }
            catch
            {
                // A corrupt or inaccessible settings file must not prevent startup.
            }
        }

        private void SaveSettings()
        {
            try
            {
                SizeOption size = (SizeOption)maxSizeCombo.SelectedItem;
                ConflictOption conflict = (ConflictOption)conflictCombo.SelectedItem;
                string settingsPath = GetSettingsPath();
                Directory.CreateDirectory(Path.GetDirectoryName(settingsPath));
                File.WriteAllLines(settingsPath, new string[]
                {
                    "Sidecar=" + (besideRadio.Checked ? "1" : "0"),
                    "Output=" + outputPathBox.Text.Trim(),
                    "Quality=" + qualityTrack.Value,
                    "MaxSize=" + (size == null ? 0 : size.Value),
                    "Conflict=" + (conflict == null ? (int)ConflictPolicy.Rename : (int)conflict.Value),
                    "EmbeddedPreview=" + (embeddedPreviewCheck.Checked ? "1" : "0"),
                    "OpenWhenDone=" + (openWhenDoneCheck.Checked ? "1" : "0")
                });
            }
            catch
            {
            }
        }

        private void OnFormClosing(object sender, FormClosingEventArgs args)
        {
            if (busy)
            {
                DialogResult answer = MessageBox.Show(
                    this,
                    "照片仍在转换中。确定要取消并退出吗？",
                    "确认退出",
                    MessageBoxButtons.YesNo,
                    MessageBoxIcon.Question);
                if (answer != DialogResult.Yes)
                {
                    args.Cancel = true;
                    return;
                }

                if (cancellationSource != null)
                {
                    cancellationSource.Cancel();
                }
            }

            SaveSettings();
            Image preview = previewBox == null ? null : previewBox.Image;
            if (preview != null)
            {
                preview.Dispose();
            }
            uiFont.Dispose();
            uiFontBold.Dispose();
            titleFont.Dispose();
        }

        protected override void OnShown(EventArgs args)
        {
            base.OnShown(args);
            try
            {
                int availableWidth = contentSplit.Width - contentSplit.SplitterWidth;
                int maximumFirstPanel = availableWidth - 290;
                contentSplit.Panel1MinSize = 500;
                contentSplit.Panel2MinSize = 290;
                contentSplit.SplitterDistance = Math.Max(
                    500,
                    Math.Min(maximumFirstPanel, (int)(availableWidth * 0.66)));
            }
            catch
            {
                // Keep the default split if a very small display cannot satisfy both minimums.
            }

            if (pendingInitialPaths.Length > 0)
            {
                AddPaths(pendingInitialPaths);
            }
        }

        private static string GetDefaultOutputDirectory()
        {
            string pictures = Environment.GetFolderPath(Environment.SpecialFolder.MyPictures);
            if (String.IsNullOrWhiteSpace(pictures))
            {
                pictures = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
            }
            return Path.Combine(pictures, "RAW转JPG输出");
        }

        private static string GetSettingsPath()
        {
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "Raw2JpgStudio",
                "settings.ini");
        }

        private static string FormatFileSize(long bytes)
        {
            if (bytes >= 1024L * 1024L * 1024L)
            {
                return String.Format("{0:0.00} GB", bytes / (1024.0 * 1024.0 * 1024.0));
            }
            if (bytes >= 1024L * 1024L)
            {
                return String.Format("{0:0.0} MB", bytes / (1024.0 * 1024.0));
            }
            if (bytes >= 1024L)
            {
                return String.Format("{0:0} KB", bytes / 1024.0);
            }
            return bytes + " B";
        }

        private static string ShortenMessage(string message, int maximumLength)
        {
            if (String.IsNullOrWhiteSpace(message))
            {
                return "";
            }

            string singleLine = message.Replace("\r", " ").Replace("\n", " ").Trim();
            if (singleLine.Length <= maximumLength)
            {
                return singleLine;
            }

            return singleLine.Substring(0, Math.Max(0, maximumLength - 1)) + "…";
        }

        private static void SelectComboValue(ComboBox comboBox, int value)
        {
            for (int index = 0; index < comboBox.Items.Count; index++)
            {
                object item = comboBox.Items[index];
                SizeOption size = item as SizeOption;
                if (size != null && size.Value == value)
                {
                    comboBox.SelectedIndex = index;
                    return;
                }

                ConflictOption conflict = item as ConflictOption;
                if (conflict != null && (int)conflict.Value == value)
                {
                    comboBox.SelectedIndex = index;
                    return;
                }
            }
        }
    }

    internal sealed class ImageJob
    {
        public string Path { get; set; }
        public long Size { get; set; }
        public string Status { get; set; }

        public ImageJob()
        {
            Status = "待转换";
        }
    }

    internal sealed class PreviewUiResult
    {
        public Bitmap Bitmap { get; set; }
        public int SourceWidth { get; set; }
        public int SourceHeight { get; set; }
        public bool UsedEmbeddedPreview { get; set; }
    }

    internal sealed class SizeOption
    {
        public string Text { get; private set; }
        public int Value { get; private set; }

        public SizeOption(string text, int value)
        {
            Text = text;
            Value = value;
        }

        public override string ToString()
        {
            return Text;
        }
    }

    internal sealed class ConflictOption
    {
        public string Text { get; private set; }
        public ConflictPolicy Value { get; private set; }

        public ConflictOption(string text, ConflictPolicy value)
        {
            Text = text;
            Value = value;
        }

        public override string ToString()
        {
            return Text;
        }
    }
}
