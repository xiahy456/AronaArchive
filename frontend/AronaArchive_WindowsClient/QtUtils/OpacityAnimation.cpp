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


#include "opacityanimation.h"

OpacityAnimation::OpacityAnimation(QWidget* widget, double opacity, int duration, QEasingCurve easingCurve) {
    // 构建对象
    this->m_opacityEffect = new QGraphicsOpacityEffect;
    this->m_animation_obj = new QPropertyAnimation(m_opacityEffect, "opacity");
    this->m_widget = widget;
    // 绑定对象
    m_widget->setGraphicsEffect(m_opacityEffect);
    // 初始化frame
    setOpacity(opacity);
    // 初始化动画对象
    m_animation_obj->setDuration(duration);   // 动画持续时间
    m_animation_obj->setEasingCurve(easingCurve);    // 缓入缓出效果
}

void OpacityAnimation::startAnimation(double start_opacity, double goal_opacity) {
    this->m_animation_obj->setStartValue(start_opacity);
    this->m_animation_obj->setEndValue(goal_opacity);
    this->m_animation_obj->start();
}

void OpacityAnimation::setOpacity(double opacity)
{
    this->m_opacityEffect->setOpacity(opacity);
    m_widget->setGraphicsEffect(m_opacityEffect);
}
