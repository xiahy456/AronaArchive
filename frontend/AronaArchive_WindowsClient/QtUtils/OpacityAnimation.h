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


#ifndef OPACITYANIMATION_H
#define OPACITYANIMATION_H

#include <QFrame>
#include <QGraphicsOpacityEffect>
#include <QPropertyAnimation>

class OpacityAnimation
{
public:
    OpacityAnimation(QWidget* widget, double opacity, int duration, QEasingCurve easingCurve);

    // 初始化不透明度，初始化动画
    void startAnimation(double start_opacity, double goal_opacity);
    // 直接设置不透明度
	void setOpacity(double opacity);

    // 控件对象指针
	QWidget* m_widget = nullptr;
    // 不透明度效果对象
    QGraphicsOpacityEffect* m_opacityEffect = nullptr;
    // 动画对象
    QPropertyAnimation* m_animation_obj = nullptr;
};

#endif // OPACITYANIMATION_H
