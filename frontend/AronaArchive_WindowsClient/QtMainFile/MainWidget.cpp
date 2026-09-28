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

#include "MainWidget.h"
#include <QTimer>

MainWidget::MainWidget(QWidget *parent)
    : QWidget(parent)
{
    FINE_DEBUG_OUTPUT("[Qt Operation]Loading MainWidget...");   // 调试信息

	// 加载UI界面
    ui.setupUi(this);

    connect(ui.qtSpineManagerWidget, &QtSpineManager::spineLoaded, this, [this]() {
        m_spineReady = true;
        emit spineReady();
    });
    auto loadSpine = [this]() {
        ui.qtSpineManagerWidget->loadSpineFile(
            GET_STRING_FROM_JSON(_global_config, "spine", "atlas_path"),
            GET_STRING_FROM_JSON(_global_config, "spine", "skelOrJson_path")
            );
        ui.qtSpineManagerWidget->setAnimation("Idle_01", 0, true);  // 基础层
        //ui.qtSpineManagerWidget->setAnimation("03", 1, true); // 调试：表情层
    };
    if (ui.qtSpineManagerWidget->isGLReady()) {
        loadSpine();
    } else {
        connect(ui.qtSpineManagerWidget, &QtSpineManager::glReady, this, loadSpine, Qt::SingleShotConnection);
    }

    // 初始化相关控件
    m_opacityAnimation_aronaOutputTextBox = new OpacityAnimation(ui.aronaOutputTextBox, 0.0, 250, QEasingCurve::Linear); // 默认气泡文本不透明度为0
    m_mouseTransparent = GET_BOOL_FROM_JSON(_global_config, "settings", "mouse_event_transparent");

    // 窗口设置
    this->setAttribute(Qt::WA_TranslucentBackground);	// 设置窗口背景透明
    this->setMouseTransparent(m_mouseTransparent);    // 设置鼠标穿透点击
    this->setWindowFlag(Qt::FramelessWindowHint);	// 设置无边框窗口
    this->setWindowFlag(Qt::WindowStaysOnTopHint);	// 设置窗口始终在顶部
    this->setWindowFlag(Qt::Tool);	// 隐藏应用程序图标
	this->setWindowTitle(GET_STRING_FROM_JSON(_global_dict, "application_data", "main_widget_name"));  // 设置窗口名称
    this->setWindowOpacity(qBound(0.0, 1.0, GET_DOUBLE_FROM_JSON(_global_config, "settings", "transparent")));  // 设置窗口整体不透明度
    
    // 设置窗口大小
	this->resize(300 * WIDGET_ZOOM, 440 * WIDGET_ZOOM);

    // 移动窗口
    // 获取主屏幕
    QScreen* screen = QApplication::primaryScreen();
    QRect screenRect = screen->availableGeometry();
    // 移动窗口
    this->move(screenRect.left() + (GET_INT_FROM_JSON(_global_config, "settings", "offset_from_screen_left") * WIDGET_ZOOM)
        , screenRect.bottom() - this->height() - GET_INT_FROM_JSON(_global_config, "settings", "offset_from_screen_bottom"));
    // 安装事件过滤器
	this->installEventFilter(this);

    // 界面控件设置
    ui.aronaOutputTextBox->resize(300 * WIDGET_ZOOM, 80 * WIDGET_ZOOM);
	ui.aronaOutputTextBox->move(0 * WIDGET_ZOOM, 270 * WIDGET_ZOOM - GET_INT_FROM_JSON(_global_config, "settings", "output_text_box_offset"));
	ui.aronaOutputText->resize(280 * WIDGET_ZOOM, 60 * WIDGET_ZOOM);
	ui.aronaOutputText->move(10 * WIDGET_ZOOM, 10 * WIDGET_ZOOM);
    ui.aronaOutputText->setFont(BlueakaFontLoader::instance()->createFont(12));
	ui.qtSpineManagerWidget->resize(220 * WIDGET_ZOOM, 440 * WIDGET_ZOOM);
	ui.qtSpineManagerWidget->move(40 * WIDGET_ZOOM, 0);
    ui.aronaOutputTextBox->setStyleSheet(
        "#aronaOutputTextBox {"
        "    border-image: url('" + GET_STRING_FROM_JSON(_global_config, "settings", "text_box_path") +  "');"
        "    background-position: center;"
        "    border: 1px solid rgb(191, 191, 191);"
        "    border-radius: 10px;"
        "}"
    );
    
    // 设置文本字体大小
	QFont font = ui.aronaOutputText->font();
	font.setPointSize(11 * WIDGET_ZOOM);
	ui.aronaOutputText->setFont(font);

	// 调试-输出文本
    debug_showText();
}

MainWidget::~MainWidget()
{
}

void MainWidget::showOutputText(const QString& text)
{
    ui.aronaOutputText->setText(text);
    if (m_outputBubbleVisible) {
        return;
    }
    m_outputBubbleVisible = true;
	m_opacityAnimation_aronaOutputTextBox->startAnimation(0.0, 0.85);
}

void MainWidget::hideOutputText()
{
    if (!m_outputBubbleVisible) {
        return;
    }
    m_outputBubbleVisible = false;
    m_opacityAnimation_aronaOutputTextBox->startAnimation(0.85, 0.0);
}

void MainWidget::setAnimation(const QString& name, int track_idx, bool loop)
{
	ui.qtSpineManagerWidget->setAnimation(name, track_idx, loop);
}

void MainWidget::clearAnimation(int track_idx, float mix_duration)
{
	ui.qtSpineManagerWidget->clearAnimation(track_idx, mix_duration);
}

void MainWidget::setMouseTransparent(bool isMouseTransparent)
{
	m_mouseTransparent = isMouseTransparent;
    if (m_mouseTransparent) {
        FINE_DEBUG_OUTPUT("[Qt Operation]Setting mouse event to transparent");
        // 穿透点击
        this->setWindowFlags(this->windowFlags() | Qt::WindowTransparentForInput);
        this->show();
    }
    else {
        FINE_DEBUG_OUTPUT("[Qt Operation]Setting mouse event to non-transparent");
		// 非穿透点击
        this->setWindowFlags(this->windowFlags() & ~Qt::WindowTransparentForInput);
        this->show();
    }
}

bool MainWidget::isMouseTransparent() const
{
	return m_mouseTransparent;
}

bool MainWidget::isSpineReady() const
{
    return m_spineReady;
}

QtSpineManager* MainWidget::spineManager() const
{
    return ui.qtSpineManagerWidget;
}

void MainWidget::debug_showText()
{
    QTimer::singleShot(1000, [this]() { showOutputText(GET_STRING_FROM_JSON(_global_dict, "debug", "initializing")); });
    // 1000ms后隐藏气泡文本
    QTimer::singleShot(1500, [this]() { hideOutputText(); });
}

void MainWidget::mousePressEvent(QMouseEvent* event)
{
    if (event->button() == Qt::RightButton) {
        m_dragging = true;
        m_dragPosition = event->globalPosition().toPoint() - frameGeometry().topLeft();
        event->accept();
    }
}

void MainWidget::mouseMoveEvent(QMouseEvent* event)
{
    if (m_dragging && (event->buttons() & Qt::RightButton)) {
        move(event->globalPosition().toPoint() - m_dragPosition);
        event->accept();
    }
}

void MainWidget::mouseReleaseEvent(QMouseEvent* event)
{
    if (event->button() == Qt::RightButton) {
        m_dragging = false;
        event->accept();
    }
}
