/*
 Copyright 2026 xia_hy456. All rights reserved.

 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

      https://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
*/

#include "SettingsWidget.h"

SettingsWidget::SettingsWidget(QWidget *parent)
	: QWidget(parent)
{
    // 加载UI界面
	ui.setupUi(this);
    
    // 窗口设置
    this->setAttribute(Qt::WA_TranslucentBackground);	// 设置窗口背景透明
    //this->setAttribute(Qt::WA_TransparentForMouseEvents, true); // 设置鼠标穿透点击
    this->setWindowFlag(Qt::FramelessWindowHint);	// 设置无边框窗口
    //this->setWindowFlag(Qt::WindowStaysOnTopHint);	// 设置窗口始终在顶部
    //this->setWindowFlag(Qt::Tool);	// 隐藏应用程序图标
    this->setAutoFillBackground(false);   // 禁用自动填充背景
    this->setWindowTitle(GET_STRING_FROM_JSON(_global_dict, "application_data", "settings_widget_name"));  // 设置窗口名称

    // 设置窗口大小
    this->resize(1080 * WIDGET_ZOOM, 410 * WIDGET_ZOOM);

    // 控件设置
    // 界面切换按钮
    WIDGET_SWITCH_SETTING(ui.basicSettingsButton, 0);
    WIDGET_SWITCH_SETTING(ui.aronaLMSettingsButton, 1);
    WIDGET_SWITCH_SETTING(ui.spineSettingsButton, 2);
    WIDGET_SWITCH_SETTING(ui.gptSOVITSSettingsButton, 3);
    WIDGET_SWITCH_SETTING(ui.debugOutputButton, 4);
    WIDGET_SWITCH_SETTING(ui.aboutDeveloperButton, 5);
    ui.basicSettingsButton->setText(GET_STRING_FROM_JSON(_global_dict, "application_data", "basic_settings_button_name"));
    ui.aronaLMSettingsButton->setText(GET_STRING_FROM_JSON(_global_dict, "application_data", "arona_lm_settings_button_name"));
    ui.spineSettingsButton->setText(GET_STRING_FROM_JSON(_global_dict, "application_data", "spine_settings_button_name"));
    ui.gptSOVITSSettingsButton->setText(GET_STRING_FROM_JSON(_global_dict, "application_data", "gpt_sovits_settings_button_name"));
    ui.debugOutputButton->setText(GET_STRING_FROM_JSON(_global_dict, "application_data", "debug_output_button_name"));
    ui.aboutDeveloperButton->setText(GET_STRING_FROM_JSON(_global_dict, "application_data", "about_developer_button_name"));

    // 上方栏
    ui.topInformationWidget->move(130 * WIDGET_ZOOM, 0 * WIDGET_ZOOM);
    ui.topInformationWidget->resize(940 * WIDGET_ZOOM, 25 * WIDGET_ZOOM);
    ui.topInformationWidget->setStyleSheet(
        "QWidget{"
        "background-color: rgb(250, 251, 253);"
        "border-image: url(" + GET_STRING_FROM_JSON(_global_config, "settings", "top_information_path") + ");"
        "border: none;"
        "border-bottom-left-radius: 8px;"
        "border-bottom-right-radius: 8px;"
        "}"
    );

    ui.topInformationShadowWidget->move(130 * WIDGET_ZOOM, 3 * WIDGET_ZOOM);
    ui.topInformationShadowWidget->resize(940 * WIDGET_ZOOM, 25 * WIDGET_ZOOM);

    ui.closeButton->move(1040 * WIDGET_ZOOM, 3 * WIDGET_ZOOM);
    ui.closeButton->resize(19 * WIDGET_ZOOM, 19 * WIDGET_ZOOM);
    ui.closeButton->setStyleSheet(
        "QPushButton {"
        "border: none;"
        "border-image: url(" + GET_STRING_FROM_JSON(_global_config, "settings", "close_button_path") + ");"
        "border-radius: " + (QString::number(8 * WIDGET_ZOOM)) + "px; "
        "}"
    );

    ui.widgetNameLabel->move(140 * WIDGET_ZOOM, 0 * WIDGET_ZOOM);
    ui.widgetNameLabel->resize(240 * WIDGET_ZOOM, 25 * WIDGET_ZOOM);
    ui.widgetNameLabel->setFont(BlueakaFontLoader::instance()->createFont(12 * WIDGET_ZOOM));
    ui.widgetNameLabel->setText(GET_STRING_FROM_JSON(_global_dict, "application_data", "settings_widget_name"));
    ui.widgetNameLabel->setStyleSheet("color: rgb(44, 69, 99); ");

    // 主界面背景
    ui.mainBGWidget->move(80 * WIDGET_ZOOM, 20 * WIDGET_ZOOM);
    ui.mainBGWidget->setFixedSize(990 * WIDGET_ZOOM, 380 * WIDGET_ZOOM);
    ui.mainBGWidget->setFillBackground(true);
    ui.mainBGWidget->setBackgroundImage(GET_STRING_FROM_JSON(_global_config, "settings", "settings_bg_path"));

	ui.mainBGShadowWidget->move(80 * WIDGET_ZOOM, 400 * WIDGET_ZOOM);
	ui.mainBGShadowWidget->resize(772 * WIDGET_ZOOM, 3 * WIDGET_ZOOM);

    // stackedWidget控件
	ui.stackedWidget->move(80 * WIDGET_ZOOM, 20 * WIDGET_ZOOM);
	ui.stackedWidget->resize(990 * WIDGET_ZOOM, 380 * WIDGET_ZOOM);
    ui.stackedWidget->setCurrentIndex(0);

    // 基础设置控件
    // 帧率
    WIDGET_CHILD_SETTING_LABEL(ui.basicSettings_frameRateLabel, "frame_rate", 0);
    WIDGET_CHILD_SETTING_INPUT_NUMBER(ui.basicSettings_frameRateLineEdit, "settings", "frame_rate", 0);

    // 界面缩放
    WIDGET_CHILD_SETTING_LABEL(ui.basicSettings_widgetZoomLabel, "widget_zoom", 1);
    WIDGET_CHILD_SETTING_INPUT_NUMBER(ui.basicSettings_widgetZoomLabelLineEdit, "settings", "zoom", 1);

    // 语音快捷键
    WIDGET_CHILD_SETTING_LABEL(ui.basicSettings_shortCutLabel, "voiceInput_shortCut", 2);
    WIDGET_CHILD_SETTING_INPUT_STRING(ui.basicSettings_shortCutLineEdit, "short_cut_key", "switch_audio_input", 2);

	// 运行模式
    ui.basicSettings_aronaAIModeWidget->move(STEP_POSITION_POINT(230, 20, 40, 3));  // 运行模式设置控件基准位置
	ui.basicSettings_aronaAIModeWidget->resize(400 * WIDGET_ZOOM, 120 * WIDGET_ZOOM);
    ui.basicSettings_aronaAIModeWidget->setStyleSheet("color: rgb(44, 69, 99);");

    ui.basicSettings_aronaAIModeLabel->move(0, 0);
    ui.basicSettings_aronaAIModeLabel->resize(140 * WIDGET_ZOOM, 24 * WIDGET_ZOOM);
    ui.basicSettings_aronaAIModeLabel->setFont(BlueakaFontLoader::instance()->createFont(11 * WIDGET_ZOOM));
    ui.basicSettings_aronaAIModeLabel->setText(GET_STRING_FROM_JSON(_global_dict, "settings", "arona_ai_mode"));

    ui.basicSettings_aronaAIModeSwitchBGWidget->move(STEP_POSITION_POINT(140, 0, 0, 0));
    ui.basicSettings_aronaAIModeSwitchBGWidget->setFixedSize(WIDTH_X(142, 24), 26 * WIDGET_ZOOM);
    ui.basicSettings_aronaAIModeSwitchBGWidget->setFillBackground(true);
    ui.basicSettings_aronaAIModeSwitchBGWidget->setFillColor(QColor(240, 240, 240));

    ui.basicSettings_aronaAIModePSLabel_0->move(0, 30 * WIDGET_ZOOM);
    ui.basicSettings_aronaAIModePSLabel_0->resize(400 * WIDGET_ZOOM, 15 * WIDGET_ZOOM);
    ui.basicSettings_aronaAIModePSLabel_0->setFont(BlueakaFontLoader::instance()->createFont(8 * WIDGET_ZOOM));

    ui.basicSettings_aronaAIModePSLabel_1->move(0, 45 * WIDGET_ZOOM);
    ui.basicSettings_aronaAIModePSLabel_1->resize(400 * WIDGET_ZOOM, 15 * WIDGET_ZOOM);
    ui.basicSettings_aronaAIModePSLabel_1->setFont(BlueakaFontLoader::instance()->createFont(8 * WIDGET_ZOOM));

    ui.basicSettings_aronaAIModePSLabel_2->move(-3 * WIDGET_ZOOM, 60 * WIDGET_ZOOM);
    ui.basicSettings_aronaAIModePSLabel_2->resize(400 * WIDGET_ZOOM, 15 * WIDGET_ZOOM);
    ui.basicSettings_aronaAIModePSLabel_2->setFont(BlueakaFontLoader::instance()->createFont(8 * WIDGET_ZOOM));
    ui.basicSettings_aronaAIModePSLabel_2->setStyleSheet("color: rgb(58, 91, 130);");

    ui.basicSettings_aronaAIModeSwitchButton->setFixedSize(WIDTH_X(80, 24), 24 * WIDGET_ZOOM);
    ui.basicSettings_aronaAIModeSwitchButton->setImageScaleMode(Qt::IgnoreAspectRatio);
    ui.basicSettings_aronaAIModeSwitchButton->setFont(BlueakaFontLoader::instance()->createFont(11 * WIDGET_ZOOM));
    int aronaAIModeIndex = GET_INT_FROM_JSON(_global_config, "settings", "arona_ai_mode");
    switch (aronaAIModeIndex) {
    case 0:
        ui.basicSettings_aronaAIModeSwitchButton->move(2 * WIDGET_ZOOM, 1 * WIDGET_ZOOM);
        ui.basicSettings_aronaAIModeSwitchButton->setText(GET_STRING_FROM_JSON(_global_dict, "settings", "arona_ai_mode_0"));
        ui.basicSettings_aronaAIModeSwitchButton->setBackgroundImage(GET_STRING_FROM_JSON(_global_config, "settings", "arona_ai_mode_switch_button_0"));
        ui.basicSettings_aronaAIModePSLabel_0->setText(GET_STRING_FROM_JSON(_global_dict, "formed_text", "arona_ai_mode_0_text_0"));
        ui.basicSettings_aronaAIModePSLabel_1->setText(GET_STRING_FROM_JSON(_global_dict, "formed_text", "arona_ai_mode_0_text_1"));
        ui.basicSettings_aronaAIModePSLabel_2->setText(GET_STRING_FROM_JSON(_global_dict, "formed_text", "arona_ai_mode_0_text_2"));
        break;
    case 1:
        ui.basicSettings_aronaAIModeSwitchButton->move(60 * WIDGET_ZOOM, 1 * WIDGET_ZOOM);
        ui.basicSettings_aronaAIModeSwitchButton->setText(GET_STRING_FROM_JSON(_global_dict, "settings", "arona_ai_mode_1"));
        ui.basicSettings_aronaAIModeSwitchButton->setBackgroundImage(GET_STRING_FROM_JSON(_global_config, "settings", "arona_ai_mode_switch_button_1"));
        ui.basicSettings_aronaAIModePSLabel_0->setText(GET_STRING_FROM_JSON(_global_dict, "formed_text", "arona_ai_mode_1_text_0"));
        ui.basicSettings_aronaAIModePSLabel_1->setText(GET_STRING_FROM_JSON(_global_dict, "formed_text", "arona_ai_mode_1_text_1"));
        ui.basicSettings_aronaAIModePSLabel_2->setText(GET_STRING_FROM_JSON(_global_dict, "formed_text", "arona_ai_mode_1_text_2"));
        break;
    };

	// AronaLM设置控件

	// Spine设置控件

	// GPT-SOVITS设置控件

	// 调试输出控件
    ui.debugOutput_outputTextBrowser->setFont(BlueakaFontLoader::instance()->createFont(9 * WIDGET_ZOOM));

	// 关于开发者控件
    // 开发者
    WIDGET_CHILD_SETTING_LABEL(ui.aboutDeveloper_developerLable, "developer", 0);
    ui.aboutDeveloper_developerLable->move(STEP_POSITION_POINT(230, 58, 100, 0));
    
    // 原作
    WIDGET_CHILD_SETTING_LABEL(ui.aboutDeveloper_originLable, "origin", 1);
    ui.aboutDeveloper_originLable->move(STEP_POSITION_POINT(230, 58, 100, 1));

    ui.aboutDeveloper_originWidget->move(STEP_POSITION_POINT(280, 20, 100, 1));
	ui.aboutDeveloper_originWidget->resize(200 * WIDGET_ZOOM, 100 * WIDGET_ZOOM);
    ui.aboutDeveloper_originWidget->setStyleSheet(
        "QWidget{"
        "border-image: url(" + GET_STRING_FROM_JSON(_global_config, "settings", "origin_logo_path") + ");"
        "border: none;"
        "}"
    );

    // 连接信号与槽
    connect(ui.closeButton, &QPushButton::clicked, this, &SettingsWidget::onCloseButtonClicked);    // CloseButton
	connect(ui.basicSettingsButton, &QPushButton::clicked, this, &SettingsWidget::onBasicSettingsButtonClicked);    // 基础设置按钮
	connect(ui.aronaLMSettingsButton, &QPushButton::clicked, this, &SettingsWidget::onAronaLMSettingsButtonClicked);    // AronaLM设置按钮
	connect(ui.spineSettingsButton, &QPushButton::clicked, this, &SettingsWidget::onSpineSettingsButtonClicked);    // Spine设置按钮
	connect(ui.gptSOVITSSettingsButton, &QPushButton::clicked, this, &SettingsWidget::onGptSOVITSSettingsButtonClicked);    // GPT-SOVITS设置按钮
	connect(ui.debugOutputButton, &QPushButton::clicked, this, &SettingsWidget::onDebugOutputButtonClicked);    // 调试输出按钮
	connect(ui.aboutDeveloperButton, &QPushButton::clicked, this, &SettingsWidget::onAboutDeveloperButtonClicked);    // 关于开发者按钮
	connect(ui.basicSettings_aronaAIModeSwitchButton, &QPushButton::clicked, this, &SettingsWidget::onAronaAIModeSwitchButtonClicked);    // 运行模式切换按钮
    connect(DebugManager::instance(), &DebugManager::debugMessageReceived, this, &SettingsWidget::receiveDebugMessage); // 接收调试输出
    
    // 重放缓存的消息
    DebugManager::instance()->flushPendingMessages();

}

SettingsWidget::~SettingsWidget()
{

}

void SettingsWidget::closeEvent(QCloseEvent * event)
{
    // 忽略关闭事件，改为隐藏窗口
    event->ignore();
    this->hide();
}

void SettingsWidget::mousePressEvent(QMouseEvent* event)
{
    // 检查是否点击在可拖动的控件上
    if (ui.topInformationWidget && ui.topInformationWidget->geometry().contains(event->pos()))
    {
        m_isDragging = true;
        m_dragPosition = event->globalPosition() - frameGeometry().topLeft();
        event->accept();
    }
    else
    {
        QWidget::mousePressEvent(event);
    }
}

void SettingsWidget::mouseMoveEvent(QMouseEvent* event)
{
    if (m_isDragging && (event->buttons() & Qt::LeftButton))
    {
        move((event->globalPosition() - m_dragPosition).toPoint());
        event->accept();
    }
    else
    {
        QWidget::mouseMoveEvent(event);
    }
}

void SettingsWidget::mouseReleaseEvent(QMouseEvent* event)
{
    if (m_isDragging)
    {
        m_isDragging = false;
        event->accept();
    }
    else
    {
        QWidget::mouseReleaseEvent(event);
    }
}

void SettingsWidget::onBasicSettingsButtonClicked()
{
    // 切换页面
    ui.stackedWidget->setCurrentIndex(0);
}

void SettingsWidget::onAronaLMSettingsButtonClicked()
{
    // 切换页面
    ui.stackedWidget->setCurrentIndex(1);
}

void SettingsWidget::onSpineSettingsButtonClicked()
{    // 切换页面
    ui.stackedWidget->setCurrentIndex(2);
}

void SettingsWidget::onGptSOVITSSettingsButtonClicked()
{    // 切换页面
    ui.stackedWidget->setCurrentIndex(3);
}

void SettingsWidget::onDebugOutputButtonClicked()
{    // 切换页面
    ui.stackedWidget->setCurrentIndex(4);
}

void SettingsWidget::onAboutDeveloperButtonClicked()
{    // 切换页面
    ui.stackedWidget->setCurrentIndex(5);
}

void SettingsWidget::onAronaAIModeSwitchButtonClicked()
{
    // 获取当前状态
	int currentModeIdx = GET_INT_FROM_JSON(_global_config, "settings", "arona_ai_mode");
    int timeLast = 500; // 位移动画持续时间
    // 播放按键动画
    if (!currentModeIdx) {
		// 助手模式->档案模式
        // 前置状态保证
        ui.basicSettings_aronaAIModeSwitchButton->setText(GET_STRING_FROM_JSON(_global_dict, "settings", "arona_ai_mode_0"));
        // 位移动画
        QPropertyAnimation* animation_aronaAIModeSwitchButton_0_1 = new QPropertyAnimation(ui.basicSettings_aronaAIModeSwitchButton, "pos");
        animation_aronaAIModeSwitchButton_0_1->setDuration(timeLast);
        animation_aronaAIModeSwitchButton_0_1->setStartValue(QPoint(2 * WIDGET_ZOOM, 1 * WIDGET_ZOOM));
        animation_aronaAIModeSwitchButton_0_1->setEndValue(QPoint(60 * WIDGET_ZOOM, 1 * WIDGET_ZOOM));
        animation_aronaAIModeSwitchButton_0_1->setEasingCurve(QEasingCurve::InOutQuint);
        animation_aronaAIModeSwitchButton_0_1->start();
        // 瞬时更改
        QTimer::singleShot(timeLast/2, [this]() {
            ui.basicSettings_aronaAIModeSwitchButton->setText(GET_STRING_FROM_JSON(_global_dict, "settings", "arona_ai_mode_1"));
            ui.basicSettings_aronaAIModeSwitchButton->setBackgroundImage(GET_STRING_FROM_JSON(_global_config, "settings", "arona_ai_mode_switch_button_1"));
            ui.basicSettings_aronaAIModePSLabel_0->setText(GET_STRING_FROM_JSON(_global_dict, "formed_text", "arona_ai_mode_1_text_0"));
            ui.basicSettings_aronaAIModePSLabel_1->setText(GET_STRING_FROM_JSON(_global_dict, "formed_text", "arona_ai_mode_1_text_1"));
            ui.basicSettings_aronaAIModePSLabel_2->setText(GET_STRING_FROM_JSON(_global_dict, "formed_text", "arona_ai_mode_1_text_2"));
            });
        // 设置_global_config
        if (!SET_INT_TO_JSON(_global_config, "settings", "arona_ai_mode", 1)) qWarning() << ERROR_PR << "[Setting Widget]Set arona AI mode to 1 failed!";
    }
    else {
        // 助手模式<-档案模式
        // 前置状态保证
        ui.basicSettings_aronaAIModeSwitchButton->setText(GET_STRING_FROM_JSON(_global_dict, "settings", "arona_ai_mode_1"));
        // 位移动画
        QPropertyAnimation* animation_aronaAIModeSwitchButton_1_0 = new QPropertyAnimation(ui.basicSettings_aronaAIModeSwitchButton, "pos");
        animation_aronaAIModeSwitchButton_1_0->setDuration(timeLast);
        animation_aronaAIModeSwitchButton_1_0->setStartValue(QPoint(60 * WIDGET_ZOOM, 1 * WIDGET_ZOOM));
        animation_aronaAIModeSwitchButton_1_0->setEndValue(QPoint(2 * WIDGET_ZOOM, 1 * WIDGET_ZOOM));
        animation_aronaAIModeSwitchButton_1_0->setEasingCurve(QEasingCurve::InOutQuint);
        animation_aronaAIModeSwitchButton_1_0->start();
        // 瞬时更改
        QTimer::singleShot(timeLast / 2, [this]() {
            ui.basicSettings_aronaAIModeSwitchButton->setText(GET_STRING_FROM_JSON(_global_dict, "settings", "arona_ai_mode_0"));
            ui.basicSettings_aronaAIModeSwitchButton->setBackgroundImage(GET_STRING_FROM_JSON(_global_config, "settings", "arona_ai_mode_switch_button_0"));
            ui.basicSettings_aronaAIModePSLabel_0->setText(GET_STRING_FROM_JSON(_global_dict, "formed_text", "arona_ai_mode_0_text_0"));
            ui.basicSettings_aronaAIModePSLabel_1->setText(GET_STRING_FROM_JSON(_global_dict, "formed_text", "arona_ai_mode_0_text_1"));
            ui.basicSettings_aronaAIModePSLabel_2->setText(GET_STRING_FROM_JSON(_global_dict, "formed_text", "arona_ai_mode_0_text_2"));
            });
        // 设置_global_config
        if (!SET_INT_TO_JSON(_global_config, "settings", "arona_ai_mode", 0)) qWarning() << ERROR_PR << "[Setting Widget]Set arona AI mode to 0 failed!";
    }
}

void SettingsWidget::receiveDebugMessage(const QString& message)
{
    // 追加文字
    ui.debugOutput_outputTextBrowser->append(message);
}

void SettingsWidget::onCloseButtonClicked()
{
    this->hide();
}