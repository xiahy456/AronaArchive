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

#ifndef PARALLELOGRAMBUTTON_H
#define PARALLELOGRAMBUTTON_H

#include <QPushButton>
#include <QPainter>
#include <QPainterPath>
#include <QEvent>
#include <QMouseEvent>

class ParallelogramButton : public QPushButton
{
    Q_OBJECT
public:
    explicit ParallelogramButton(QWidget* parent = nullptr);

    void setShearValue(qreal shear);
    void setFillColor(const QColor& color);
    void setHoverColor(const QColor& color);
    void setPressedColor(const QColor& color);
    void setBackgroundImage(const QString& imagePath);
    void setBackgroundImage(const QPixmap& pixmap);
    void setImageScaleMode(Qt::AspectRatioMode mode);  // 图片缩放模式
    void setTextColor(const QColor& color);
	void setBorderWidth(int width);

protected:
    void paintEvent(QPaintEvent* event) override;
    void enterEvent(QEnterEvent* event) override;
    void leaveEvent(QEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;

private:
    qreal m_shear;          // 倾斜系数
    QColor m_fillColor;     // 填充颜色
    QColor m_hoverColor;    // 悬停颜色
    QColor m_pressedColor;  // 按下颜色
    bool m_isHovered;       // 是否悬停
    bool m_isPressed;       // 是否按下
    QPixmap m_backgroundImage;  // 背景图片
    bool m_hasBackgroundImage;  // 是否有背景图片
    Qt::AspectRatioMode m_imageScaleMode;  // 图片缩放模式
    QColor m_textColor = QColor(44, 69, 99);  // 默认深蓝色
    int m_borderWidth = 0;
};

#endif