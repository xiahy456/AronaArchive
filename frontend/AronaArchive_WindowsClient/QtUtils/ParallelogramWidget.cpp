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

#include "ParallelogramWidget.h"
#include <QPainter>
#include <QDebug>

ParallelogramWidget::ParallelogramWidget(QWidget* parent)
    : QWidget(parent)
    , m_skewFactor(0.5774)      // 默认倾斜系数0.5774
    , m_fillColor(Qt::white)  // 默认填充蓝色
    , m_borderColor(Qt::black) // 默认边框黑色
    , m_borderWidth(0)        // 默认边框宽度0像素
    , m_hasBackgroundImage(false)
    , m_imageScaleMode(Qt::IgnoreAspectRatio)  // 默认裁剪模式
{
    setWindowFlags(Qt::FramelessWindowHint);
    setAttribute(Qt::WA_TranslucentBackground);
    // 设置默认大小
    setFixedSize(200, 100);
}

void ParallelogramWidget::setSkewFactor(double factor)
{
    if (qFuzzyCompare(m_skewFactor, factor))
        return;

    m_skewFactor = factor;
    update();  // 触发重绘
}

void ParallelogramWidget::setFillColor(const QColor& color)
{
    if (m_fillColor == color)
        return;

    m_fillColor = color;
    update();
}

void ParallelogramWidget::setFillBackground(bool fill)
{
    m_fillBackground = fill;
    update();
}

void ParallelogramWidget::setBorderColor(const QColor& color)
{
    if (m_borderColor == color)
        return;

    m_borderColor = color;
    update();
}

void ParallelogramWidget::setBorderWidth(int width)
{
    if (m_borderWidth == width)
        return;

    m_borderWidth = width;
    update();
}

void ParallelogramWidget::setBorderPosition(bool top, bool bottom, bool left, bool right)
{
    is_top_border = top;
    is_bottom_border = bottom;
    is_left_border = left;
    is_right_border = right;
    update();
}

void ParallelogramWidget::setFixedSize(int w, int h)
{
    QWidget::setFixedSize(w, h);
    update();  // 大小改变时更新绘制
}

void ParallelogramWidget::setFixedSize(const QSize& size)
{
    QWidget::setFixedSize(size);
    update();
}

void ParallelogramWidget::setBackgroundImage(const QString& imagePath)
{
    QPixmap pixmap(imagePath);
    if (!pixmap.isNull()) {
        m_backgroundImage = pixmap;
        m_hasBackgroundImage = true;
        update();
    }
}

void ParallelogramWidget::setBackgroundImage(const QPixmap& pixmap)
{
    if (!pixmap.isNull()) {
        m_backgroundImage = pixmap;
        m_hasBackgroundImage = true;
        update();
    }
}

QPainterPath ParallelogramWidget::createParallelogramPath() const
{
    QPainterPath path;

    int w = width();
    int h = height();

    // 计算倾斜偏移量（基于高度和倾斜系数）
    int skewOffset = static_cast<int>(h * m_skewFactor);

    // 定义平行四边形的四个顶点
    // 从左上角开始，顺时针或逆时针
    QPointF topLeft(skewOffset, 0);
    QPointF topRight(w, 0);
    QPointF bottomRight(w - skewOffset, h);
    QPointF bottomLeft(0, h);

    // 构建路径
    path.moveTo(topLeft);
    path.lineTo(topRight);
    path.lineTo(bottomRight);
    path.lineTo(bottomLeft);
    path.closeSubpath();

    return path;
}

void ParallelogramWidget::paintEvent(QPaintEvent* event)
{
    // 宽高倾斜度与各个顶点
    int w = width();
    int h = height();
    int skewOffset = static_cast<int>(h * m_skewFactor);
    QPointF topLeft(skewOffset, 0);
    QPointF topRight(w, 0);
    QPointF bottomRight(w - skewOffset, h);
    QPointF bottomLeft(0, h);

    Q_UNUSED(event);

    QPainter painter(this);

    // 启用抗锯齿，使边缘更平滑
    painter.setRenderHint(QPainter::Antialiasing, true);

    // 创建平行四边形路径
    QPainterPath path = createParallelogramPath();

    // 绘制背景
    if (m_fillBackground) {
        if (m_hasBackgroundImage && !m_backgroundImage.isNull()) {
            // 方法1：使用图片作为背景填充
            painter.save();
            painter.setClipPath(path);  // 设置裁剪区域为平行四边形

            // 缩放图片以适应控件大小
            QPixmap scaledPixmap;
            if (m_imageScaleMode == Qt::IgnoreAspectRatio) {
                // 拉伸填充
                scaledPixmap = m_backgroundImage.scaled(width(), height(),
                    Qt::IgnoreAspectRatio,
                    Qt::SmoothTransformation);
            }
            else {
                // 保持比例
                scaledPixmap = m_backgroundImage.scaled(width(), height(),
                    m_imageScaleMode,
                    Qt::SmoothTransformation);
            }

            painter.drawPixmap(0, 0, scaledPixmap);
            painter.restore();
        }
        else {
            // 使用纯色填充（原有逻辑）
            painter.fillPath(path, m_fillColor);
        }
    }

    // 绘制边框
    if (m_borderWidth > 0) {
        if (is_top_border) {
            QPen topPen(m_borderColor, m_borderWidth);
            painter.setPen(topPen);
            painter.drawLine(topLeft, topRight);
        }
        if (is_bottom_border) {
            QPen bottomPen(m_borderColor, m_borderWidth);
            painter.setPen(bottomPen);
            painter.drawLine(bottomLeft, bottomRight);
        }
        if (is_left_border) {
            QPen leftPen(m_borderColor, m_borderWidth);
            painter.setPen(leftPen);
            painter.drawLine(topLeft, bottomLeft);
        }
        if (is_right_border) {
            QPen rightPen(m_borderColor, m_borderWidth);
            painter.setPen(rightPen);
            painter.drawLine(topRight, bottomRight);
        }
    }
}

void ParallelogramWidget::resizeEvent(QResizeEvent* event)
{
    QWidget::resizeEvent(event);
    // 大小改变时，可以在这里添加额外的处理逻辑
    // update() 会自动被调用
}