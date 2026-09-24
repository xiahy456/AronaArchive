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

#include "Defines.h"
#include "MainWidget.h"
#include "UserInputWidget.h"
#include "SystemTray.h"
#include "MainController.h"
#include "TTSManager.h"
#include "AudioRecorder.h"
#include "TencentSpeechRecognizer.h"
#include "ShortCutKey.h"
#include "BlueakaFontLoader.h"
#include "WebSocketController.h"
#include "StartWidget.h"

#include <QtWidgets/QApplication>
#include <QDebug>
#include <QString>
#include <QJsonObject>
#include <QElapsedTimer>
#include <QPointer>

#include <GlobalInclude.h>

// 获取全局配置
void getConfig()
{
    _global_config = new JsonOperation("Config/config.json");
}

// 获取字典
QString getDict() {
	// 获取字典路径并加载字典
    QString dict_path = GET_STRING_FROM_JSON(_global_config, "settings", "dict_path");
    _global_dict = new JsonOperation(dict_path);
	// 识别语言类型并返回语言名称
    if (dict_path.endsWith("zh.json", Qt::CaseInsensitive)) return "Chinese";
    if (dict_path.endsWith("en.json", Qt::CaseInsensitive)) return "English";
}

// 加载Blueaka字体
void loadBlueakaFont() {
    QString blueaka_fontDir = GET_STRING_FROM_JSON(_global_config, "settings", "font_path");
    if (BlueakaFontLoader::instance()->loadFromDirectory(blueaka_fontDir)) {
        FINE_DEBUG_OUTPUT("[Font Loader]Fonts loaded successfully!");
        FINE_DEBUG_OUTPUT("[Font Loader]Head of font families:" + BlueakaFontLoader::instance()->getFontFamilies()[0]);
    }
    else {
        ERROR_DEBUG_OUTPUT("[Font Loader]Failed to load Blueaka fonts, using system fonts");
    }
}

// 程序入口main函数
int main(int argc, char *argv[])
{
    // 输出启动信息
    FINE_DEBUG_OUTPUT("[Qt Operation]Starting application...");

    // 优先使用 FFmpeg 后端，避免 Windows 媒体后端对 .mov 只解出一帧就 EndOfMedia
    qputenv("QT_MEDIA_BACKEND", "ffmpeg");

	// 设置OpenGL格式，启用抗锯齿和透明度支持
    OPENGL_INITIALLIZE;

	// 创建应用程序对象
    QApplication app(argc, argv);

    QElapsedTimer startupTotal;
    QElapsedTimer startupPhase;
    startupTotal.start();
    startupPhase.start();

    // 获取配置信息
    getConfig();

    // 获取字典信息
    FINE_DEBUG_OUTPUT("[Qt Operation]Load dictionary succeed! Changing to language: " + getDict());
    FINE_DEBUG_OUTPUT(QString("[Startup] Config+dict: %1 ms (total %2 ms)")
        .arg(startupPhase.restart())
        .arg(startupTotal.elapsed()));

    // 应用程序初始化
    APPLICATION_INITIALLIZE;

    // 加载Blueaka字体
    loadBlueakaFont();
    FINE_DEBUG_OUTPUT(QString("[Startup] Fonts: %1 ms (total %2 ms)")
        .arg(startupPhase.restart())
        .arg(startupTotal.elapsed()));

    // 创建启动界面对象
    QPointer<StartWidget> startWidget = new StartWidget;
    startWidget->show();
    startWidget->raise();
    startWidget->activateWindow();
    // 先播完启动视频（主线程专供刷新），再做 MainWidget/Spine 等重加载
    startWidget->waitUntilVideoEnded();
    FINE_DEBUG_OUTPUT(QString("[Startup] Video phase: %1 ms (total %2 ms)")
        .arg(startupPhase.restart())
        .arg(startupTotal.elapsed()));
    FINE_DEBUG_OUTPUT(QString("[Qt Operation]StartWidget visible=%1").arg(startWidget && startWidget->isVisible() ? "true" : "false"));

	// 创建主窗口对象
	MainWidget* mainWidget = new MainWidget;
    QObject::connect(mainWidget, &MainWidget::spineReady, startWidget, &StartWidget::onSpineReady);
    if (mainWidget->isSpineReady()) {
        startWidget->onSpineReady();
    }

    // 创建用户输入窗口对象
    UserInputWidget* userInputWidget = new UserInputWidget;

    // 创建TTS对象
	TTSManager* ttsManager = new TTSManager;

    // 创建声音录制对象
	AudioRecorder* audioRecorder = new AudioRecorder;

	// 创建腾讯语音识别对象
    TencentSpeechRecognizer* tencentSpeechRecognizer = new TencentSpeechRecognizer;

	// 创建WebSocket控制器对象
    WebSocketController* webSocketController = new WebSocketController;
    FINE_DEBUG_OUTPUT(QString("[Startup] Widgets+services: %1 ms (total %2 ms)")
        .arg(startupPhase.restart())
        .arg(startupTotal.elapsed()));

    // 创建主控制对象（TTS 切权重与 WebSocket 并行，不再阻塞构造）
	MainController* mainController = new MainController(mainWidget, ttsManager, audioRecorder, tencentSpeechRecognizer, webSocketController, userInputWidget);
    FINE_DEBUG_OUTPUT(QString("[Startup] MainController: %1 ms (total %2 ms)")
        .arg(startupPhase.restart())
        .arg(startupTotal.elapsed()));

    if (startWidget) {
        QObject::connect(mainController, &MainController::backendConnected,
            startWidget, &StartWidget::onBackendConnected);
        QObject::connect(mainController, &MainController::backendFailed,
            startWidget, &StartWidget::onBackendFailed);
        QObject::connect(startWidget, &StartWidget::closeFinished,
            mainController, &MainController::onSplashClosed);
        if (startWidget->hasClosed()) {
            mainController->onSplashClosed();
        }
    } else {
        mainController->onSplashClosed();
    }
    mainController->startSession();

	// 创建快捷键对象
	ShortCutKey* shortCutKey = new ShortCutKey(mainController);

    // 创建系统托盘（启动即加载；设置窗口首次打开时再创建）
    SystemTray* systemTray = new SystemTray(mainWidget, mainController);

    // 输出信息必要类实例化完毕，准备启动应用程序事件循环
    FINE_DEBUG_OUTPUT("[Qt Operation]Necessary class instantiation complete! Starting application loop...");
    FINE_DEBUG_OUTPUT(QString("[Startup] Tray+hotkeys: %1 ms (total %2 ms)")
        .arg(startupPhase.restart())
        .arg(startupTotal.elapsed()));

    // 界面显示
    mainWidget->show();
    if (GET_BOOL_FROM_JSON(_global_config, "settings", "open_setting_widget")) {
        systemTray->showSettingsWidget();
    }
    // MainWidget 同样置顶，需把启动遮罩重新抬到最前，否则会被挤到普通窗口后面
    if (startWidget) {
        startWidget->raise();
        startWidget->activateWindow();
        startWidget->onAppReady();
    }

    FINE_DEBUG_OUTPUT(QString("[Startup] Entering app.exec at %1 ms")
        .arg(startupTotal.elapsed()));

    // 开始应用程序事件循环
    return app.exec();
}
