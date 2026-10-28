# AronaArchive - 自循环 AI
# Copyright (C) 2026 xia_hy456
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later

"""Separate extractor prompts. Each call has one job."""

from __future__ import annotations

TIME_RULES = """时间写入 content 或 text（对照【当前时间】换算，禁止保留相对说法）：
- 按能确定的最细粒度写：能确定到日则写年月日（「今天 / 明天 / 后天 / 昨天 / 下周一」，如 2026年8月23日）；只能确定到月则写年月（「下个月 / 上个月 / 这个月」，如 2026年9月）；只能确定到年则写年份（「明年 / 去年」）。「下个月3号」这类已点明日的，仍写到日，不要停在月。缺少年份的绝对日期（如「8月31号」）用【当前时间】补全年份。
- 钟点可保留，但必须带日期。正确：「老师2026年8月24日下午4点睡到晚上7点」；错误：「老师今天下午4点睡到晚上7点」
- 区间写成覆盖的具体日期：未指定落在哪一天时用「或」（二选一）；连续时段用「到」。正确：「老师2026年8月22日或2026年8月23日要去医院」、「老师2026年8月31日到2026年9月6日要每天11点睡觉」；错误：「老师周末要去医院」、「老师下周要每天11点睡觉」。
- 过去时态 → 最近已发生的那个日期；将来/打算 → 即将到来的那个日期；拿不准时按即将到来的日期写
- 对话已给出带年的绝对日期则沿用，不要改成抽取当日
- 无时间含义的稳定事实（名字、偏好、生日本身）不要硬加抽取当日
- 无明确起止的周期性习惯保留周期表述（如「老师每周五加班」），不要压成某一天；若周期带有明确时段（如下周每天），则写成日期区间并保留周期
"""

FACT_SYSTEM = f"""你是记忆抽取助手。根据「用户（老师）」与「阿洛娜」的对话片段、【当前时间】，以及可选的【已有相关记忆】，提取需要长期记住或需要更新/清除的用户（老师）事实。

只输出 JSON，格式：
{{"memories":[{{"op":"upsert或delete","key":"英文蛇形键","content":"短中文陈述句","category":"preference|profile|goal|other|episodic|emotional","importance":6,"entities":["实体"]}}]}}

规则：
- 只提取已确认的精确事实（名字、偏好、约定、未完成的计划）、已确认的共处事件、已确认的心情披露，不要闲聊、不要世界观百科。
- 无值得记忆的内容时返回 {{"memories":[]}}
- content 必须是短陈述句；delete 时可省略 content 或沿用旧内容
- importance 是 1 到 10 的整数，表示这条事实以后被想起的重要程度。拿不准就写 5。
- entities 是这条事实里的地点、人物、项目、物品，没有则空数组。
- 禁止疑问句、反问、猜测或未确认信息；错误示例：「老师喜欢什么颜色吗」
- 不要把老师的提问本身当成事实写入
- 禁止提取自伤、轻生、不想活、结束生命等危机内容
- category 含义：
  - preference：稳定偏好（颜色、食物等）
  - profile：档案信息（名字、生日等）
  - goal：老师自己未完成的计划/打算（临时意图）。不是托付给阿洛娜去做的事。
  - other：其它稳定事实
  - episodic：老师与阿洛娜的共处事件（「一起做过 X」），不是稳定档案。key 建议带日期，如 ep_20260918_fireworks。同日同主题才复用 key；跨日的相似事件必须新 key。禁止写成「老师经常和阿洛娜去看烟花」这类永恒人格。
  - emotional：已确认的心情披露 + 原因（「因 Y 感到难过/开心」），不是猜测、不是未说出口的分析。key 建议带日期，如 emo_20260918_overtime。同日同主题才复用 key；跨日的相似心情必须新 key。禁止写成「老师是个容易难过的人」这类永恒人格。
- {TIME_RULES.strip()}
- 若提供了【已有相关记忆】：
  - 同主题新事实与旧记忆冲突时必须二选一：复用旧 key 做 upsert，或对旧 key 输出 op=delete 后再 upsert 新 key。禁止让冲突的旧记忆继续存在。
  - 优先复用已有记忆的 key；仅当主题全新时才新建 key
  - 对照集里出现的同主题旧条目，若本轮要写入新事实，必须在输出中点名（upsert 或 delete），不要默不作声地另开一条
  - goal：对话表明该计划已执行、正在执行或已取消时，对该 goal 的 key 输出 op=delete，不要再 upsert。对照集里的过期/已完成 goal 必须 delete
  - 已发生且无后续待办的事实不要写成 goal（例如「老师成功加入了社团」用 episodic 或 other），并 delete 对照集里同主题的旧 goal。若老师只是答应以后再做，不算已完成，不要 delete
- 高频稳定 key（若适用请直接使用）：user_name、preference_color、user_birthday
- 只记录与用户（老师）相关的记忆；例如「老师喜欢蓝色」
- 记忆必须来自于用户（老师）所述。对于阿洛娜口述的老师记忆，除非得到老师肯定，否则判定为无效。
- 老师托付给阿洛娜去做的提醒，不要写成 goal。那条路另有记录。
"""

STATE_SYSTEM = f"""你维护老师当前处境的句子列表。输入是这一批对话、【当前时间】和【现有状态】。

只输出 JSON：
{{"items":[{{"op":"upsert","id":"st_travel","text":"老师在深圳出差，2026年10月27日到的。","importance":7,"source_key":"ep_20261027_shenzhen"}},{{"op":"delete","id":"st_at_home"}}]}}

规则：
- 没有需要新增、改写或删除的状态时返回 {{"items":[]}}
- text 必须是一句可以直接告诉阿洛娜的陈述，主语用「老师」。禁止「所在地：」「状态：」「当前：」这类前缀，禁止键值对，禁止换行，禁止把几件事塞进一句。
- 一句话只讲一件事。地点、身体、工作、作息分开写。
- 只在这句话改变了老师的当前处境时 upsert：换地点、换正在做的事、换作息、健康变化、情绪基调变化、重要人物变化。
- 稳定偏好不写在这里。一次性发生过的事本身不写在这里。
- id 用英文蛇形，表达这句话讲什么。改写同一件事时复用旧 id；新的处境用新 id。
- 已有同义句子时，先 delete 旧 id，再 upsert 新句。
- 列表将满时，先 delete 最不重要的一条。
- 带「待确认」且与本轮相关的旧状态，判断是否仍成立；不成立就 delete，仍成立可以不输出。
- importance 是 1 到 10。source_key 指向支撑这句话的事实 key，没有就留空字符串。
- {TIME_RULES.strip()}
- text 里禁止出现「今天」「最近」「这几天」。状态会一直被读到，相对时间过几天就会变成错的。
"""

COMMITMENT_SYSTEM = """你记录老师托付给阿洛娜去做的事。输入是这一批对话、【当前时间】和【生效中的承诺】。

只输出 JSON：
{"items":[{"op":"create","what":"提醒老师吃药","rrule":"daily","at_time":"21:00","weekday":null,"id":""},{"op":"ack","id":"cm_x","result":"done"},{"op":"cancel","id":"cm_x"},{"op":"mute","id":"cm_x"}]}

规则：
- 没有新的托付、完成或取消时返回 {"items":[]}
- 只在老师明确让阿洛娜在将来某个时点或周期性地做某事时 create。老师自己的计划不是承诺。
- rrule 只能是 daily、weekly、once。weekly 用 weekday 0 到 6（0 是周一）。at_time 用 24 小时制的 HH:MM。没有说钟点就把 at_time 留空字符串。
- 老师表示这件事已经做了，对对应 id 输出 ack。老师明确说以后别再提，输出 cancel。
- 复用【生效中的承诺】里的 id。不要自造一个已有承诺的新 id。
"""

GATE_SYSTEM = """判断老师这句话是否包含值得长期记住的信息，并指出属于哪一类。
fact       身份、偏好、作息、健康状况、共同经历、心境披露、明确的计划与约定
state      改变老师当前处境的：换地点、换在做的事、换作息、身体或情绪基调变化
commitment 老师托付阿洛娜在将来某时或周期性地做的事
寒暄、短应、对阿洛娜的提问、对阿洛娜的评价、纯操作指令都不值得记住。
只输出 JSON：{"remember": true, "kinds": ["fact", "state"]}
"""

EXTRACT_SYSTEM = FACT_SYSTEM

ALL_EXTRACT_KINDS = ("fact", "state", "commitment")
