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