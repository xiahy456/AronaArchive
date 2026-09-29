/*
 * AronaArchive - 自循环 AI
 * Copyright (C) 2026 xia_hy456
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 * SPDX-License-Identifier: GPL-3.0-or-later
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
