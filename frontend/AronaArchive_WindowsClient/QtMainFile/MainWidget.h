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

#pragma once

#include "ui_MainWidget.h"

#include <GlobalInclude.h>
#include <BlueakaFontLoader.h>

#include <QtWidgets/QWidget>
#include <QVBoxLayout>
#include <QGraphicsOpacityEffect>
#include <QPropertyAnimation>
#include <QFont>

#include <spine/QtSpineManager.h>

#include <OpacityAnimation.h>

class MainWidget : public QWidget
{
    Q_OBJECT

public:
	// 构造函数
    MainWidget(QWidget *parent = nullptr);
	// 析构函数
    ~MainWidget();
	// 显示输出文本并显示气泡（已可见时只换文本，不从 0 淡入）
	void showOutputText(const QString& text);
    // 隐藏输出文本并隐藏气泡
	void hideOutputText();
    // 设置动画
	void setAnimation(const QString& name, int track_idx, bool loop);
    // 清除动画
	void clearAnimation(int track_idx, float mix_duration);
    // 修改鼠标可用性
	void setMouseTransparent(bool isMouseTransparent);
	// 获取当前是否鼠标穿透
	bool isMouseTransparent() const;
	// Spine 是否已加载（构造期间 setMouseTransparent->show 可能已经加载完）
    bool isSpineReady() const;
    QtSpineManager* spineManager() const;

    // Debug-显示文本
	void debug_showText();

signals:
	void spineReady();

protected:
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;


private:
    Ui::MainWidgetClass ui;

    // 鼠标事件
    bool m_dragging;
    QPoint m_dragPosition;
	bool m_mouseTransparent;   // 是否鼠标穿透
	bool m_spineReady = false;	// Spine 是否已加载

    // 不透明度动画属性
	OpacityAnimation* m_opacityAnimation_aronaOutputTextBox = nullptr;   // 文本框不透明度动画
	bool m_outputBubbleVisible = false;	// 台词气泡是否已在显示（连续换句时避免从 0 淡入）

};
