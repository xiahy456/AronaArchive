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
#ifndef PARALLELOGRAMWIDGET_H
#define PARALLELOGRAMWIDGET_H

#include <QWidget>
#include <QPainter>
#include <QPainterPath>
#include <QBrush>
#include <QPen>
#include <QPixmap>

class ParallelogramWidget : public QWidget
{
    Q_OBJECT
        Q_PROPERTY(double skewFactor READ skewFactor WRITE setSkewFactor)

public:
    explicit ParallelogramWidget(QWidget* parent = nullptr);

    // 设置倾斜系数（0.0 = 矩形，正值向右倾斜，负值向左倾斜）
    void setSkewFactor(double factor);
    double skewFactor() const { return m_skewFactor; }

    // 设置填充颜色
    void setFillColor(const QColor& color);
    QColor fillColor() const { return m_fillColor; }
    void setFillBackground(bool fill);

    // 设置边框属性
    void setBorderColor(const QColor& color);
    void setBorderWidth(int width);
    void setBorderPosition(bool top = false, bool bottom = false, bool left = false, bool right = false);

    // 重写setFixedSize以保持正确绘制
    void setFixedSize(int w, int h);
    void setFixedSize(const QSize& size);

    // 设置背景图片
    void setBackgroundImage(const QString& imagePath);
    void setBackgroundImage(const QPixmap& pixmap);

protected:
    void paintEvent(QPaintEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;

private:
    QPainterPath createParallelogramPath() const;

    double m_skewFactor;      // 倾斜系数
    QColor m_fillColor;       // 填充颜色
    bool m_fillBackground = false;  // 是否填充背景
    QPixmap m_backgroundImage;  // 背景图片
    bool m_hasBackgroundImage;  // 是否有背景图片
    Qt::AspectRatioMode m_imageScaleMode;  // 图片缩放模式

    // 边框属性
    QColor m_borderColor;     // 边框颜色
    int m_borderWidth;        // 边框宽度
    bool is_top_border = false;
    bool is_bottom_border = false;
    bool is_left_border = false;
    bool is_right_border = false;
};

#endif // PARALLELOGRAMWIDGET_H