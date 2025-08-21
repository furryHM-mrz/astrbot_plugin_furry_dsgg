import asyncio

from aiocqhttp import CQHttp
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)
from astrbot.api.event import filter
from astrbot.core.utils.session_waiter import (
    session_waiter,
    SessionController,
)
from astrbot import logger
import random
import json
import os
from datetime import datetime, time
import re


@register(
    "astrbot_plugin_furry_dsgg",
    "furryhm",
    "广告助手，帮助你向所有群聊定时发送广告",
    "v1.0.0",
    "https://github.com/furryhm/astrbot_plugin_furry_dsgg",
)
class NobotPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.disable_gids: list[str] = config.get("disable_gids", [])
        self.broadcast_message = None
        self.context = context
        self.advertisements = []
        self.load_advertisements()
        self.broadcast_task = None
        self.scheduled_times = []  # 存储定时时间列表

    def load_advertisements(self):
        """加载已保存的广告内容"""
        try:
            if os.path.exists("data/furry_dsgg_ads.json"):
                with open("data/furry_dsgg_ads.json", "r", encoding="utf-8") as f:
                    self.advertisements = json.load(f)
            else:
                self.advertisements = []
        except Exception as e:
            logger.error(f"加载广告内容时出错: {e}")
            self.advertisements = []

    def save_advertisements(self):
        """保存广告内容到文件"""
        try:
            os.makedirs("data", exist_ok=True)
            with open("data/furry_dsgg_ads.json", "w", encoding="utf-8") as f:
                json.dump(self.advertisements, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存广告内容时出错: {e}")

    async def get_able_gids(self, client: CQHttp) -> list[str] | None:
        all_groups = await client.get_group_list()
        all_gids = [str(group["group_id"]) for group in all_groups]
        able_gids = [gid for gid in all_gids if gid not in self.disable_gids]
        return able_gids

    async def get_target_group(
        self, event: AiocqhttpMessageEvent, group_index: int | None = None
    ):
        """
        获取目标群组的 ID 和名称
        """
        try:
            all_groups = await event.bot.get_group_list()
            all_groups.sort(key=lambda x: x["group_id"])
            group_map = {
                str(group["group_id"]): group["group_name"] for group in all_groups
            }

            if group_index and event.is_admin():  # 仅管理员可以指定索引
                try:
                    target_group_id = str(all_groups[group_index - 1]["group_id"])
                    group_name = group_map[target_group_id]
                except IndexError:
                    logger.error("索引越界")
                    return None, None

            else:
                target_group_id = event.get_group_id()
                group_name = group_map.get(target_group_id, "未知群组")

            return target_group_id, group_name
        except Exception as e:
            logger.error(f"获取群组信息时发生错误：{e}")
            return None, None

    @filter.command("开启广告")
    async def enable_broadcast(
        self, event: AiocqhttpMessageEvent, group_index: int | None = None
    ):
        """
        开启广告，开启后当前群聊可接收来自机器人管理员的广告消息。
        """
        # 如果提供了 group_index，则关闭指定索引的群组广告；否则关闭当前群组的广告
        target_group_id, group_name = await self.get_target_group(event, group_index)
        if target_group_id is None:
            return

        if str(target_group_id) in self.disable_gids:
            self.disable_gids.remove(str(target_group_id))
            self.config.save_config()
            yield event.plain_result(f"【{group_name}】可以接收广告消息了")
        else:
            yield event.plain_result(f"【{group_name}】已开启广告，无需重复开启")

    @filter.command("关闭广告")
    async def disable_broadcast(
        self, event: AiocqhttpMessageEvent, group_index: int | None = None
    ):
        """
        关闭广告，关闭后当前群聊将不再接收来自机器人管理员的广告消息。
        """
        # 如果提供了 group_index，则关闭指定索引的群组广告；否则关闭当前群组的广告
        target_group_id, group_name = await self.get_target_group(event, group_index)
        if target_group_id is None:
            return

        if target_group_id not in self.disable_gids:
            self.disable_gids.append(str(target_group_id))
            self.config.save_config()
            yield event.plain_result(f"【{group_name}】不再接收广告消息")
        else:
            yield event.plain_result(f"【{group_name}】已关闭广告，无需重复关闭")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("广告群列表")
    async def broadcast_list(self, event: AiocqhttpMessageEvent):
        """查看将要向哪些群广告"""
        all_groups = await event.bot.get_group_list()
        all_groups.sort(key=lambda x: x["group_id"])
        able_gids_str = []
        disable_gids_str = []
        for idx, group in enumerate(all_groups, start=1):
            group_info = f"{idx}: {group['group_name']}"
            if str(group["group_id"]) in self.disable_gids:
                disable_gids_str.append(group_info)
            else:
                able_gids_str.append(group_info)

        reply = (
            "【开启广告的群聊】\n" + "\n".join(able_gids_str) + "\n\n"
            "【关闭广告的群聊】\n" + "\n".join(disable_gids_str)
        ).strip()
        yield event.plain_result(reply)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("添加广告")
    async def add_advertisement(self, event: AiocqhttpMessageEvent):
        """添加广告内容"""
        yield event.plain_result("请30秒内发送要添加的广告内容")

        @session_waiter(timeout=30, record_history_chains=True)  # type: ignore
        async def wait_for_ad_content(
            controller: SessionController, event: AiocqhttpMessageEvent
        ):
            if event.message_str == "取消":
                await event.send(event.make_result().message("已取消添加广告"))
                controller.stop()
                return

            # 存储广告内容
            ad_content = await event._parse_onebot_json(
                MessageChain(chain=event.message_obj.message)
            )
            
            # 添加时间和ID信息
            ad_entry = {
                "id": len(self.advertisements) + 1,
                "content": ad_content,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            self.advertisements.append(ad_entry)
            self.save_advertisements()
            
            await event.send(event.make_result().message(f"广告内容已添加，ID: {ad_entry['id']}"))
            controller.stop()

        try:
            await wait_for_ad_content(event)
        except TimeoutError as _:
            yield event.plain_result("等待超时！")
        except Exception as e:
            logger.error("添加广告时出错: " + str(e))
        finally:
            event.stop_event()

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("删除广告")
    async def remove_advertisement(self, event: AiocqhttpMessageEvent, ad_id: int):
        """根据ID删除广告"""
        for i, ad in enumerate(self.advertisements):
            if ad["id"] == ad_id:
                del self.advertisements[i]
                self.save_advertisements()
                yield event.plain_result(f"已删除广告 ID: {ad_id}")
                return
        yield event.plain_result(f"未找到广告 ID: {ad_id}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("广告列表")
    async def list_advertisements(self, event: AiocqhttpMessageEvent):
        """列出所有广告"""
        if not self.advertisements:
            yield event.plain_result("暂无广告内容")
            return
            
        ad_list = ["广告列表:"]
        for ad in self.advertisements:
            ad_list.append(f"ID: {ad['id']} (创建时间: {ad['created_at']})")
            
        yield event.plain_result("\n".join(ad_list))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("定时广告")
    async def schedule_advertisement(self, event: AiocqhttpMessageEvent, time_str: str = None):
        """
        设置定时广告发送，time_str为具体时间格式，如 09:00,14:30 表示在上午9点和下午2点半发送
        如果不提供参数，则显示当前设置的定时时间
        """
        if not time_str:
            if not self.scheduled_times:
                yield event.plain_result("当前未设置定时广告时间，使用方法：/定时广告 09:00,14:30")
            else:
                times_str = ", ".join([f"{t.hour:02d}:{t.minute:02d}" for t in self.scheduled_times])
                yield event.plain_result(f"当前定时广告时间：{times_str}")
            return

        # 解析时间字符串
        time_points = time_str.split(',')
        parsed_times = []
        
        for tp in time_points:
            tp = tp.strip()
            # 验证时间格式 (HH:MM)
            if not re.match(r'^([01]?[0-9]|2[0-3]):[0-5][0-9]$', tp):
                yield event.plain_result(f"时间格式错误: {tp}，正确格式如: 09:00")
                return
            hour, minute = map(int, tp.split(':'))
            parsed_times.append(time(hour, minute))
        
        # 去重并排序
        parsed_times = sorted(list(set(parsed_times)))
        self.scheduled_times = parsed_times
        
        # 停止现有的定时任务
        if self.broadcast_task and not self.broadcast_task.done():
            self.broadcast_task.cancel()
            
        # 启动新的定时任务
        if parsed_times:
            self.broadcast_task = asyncio.create_task(self._scheduled_broadcast())
            times_str = ", ".join([f"{t.hour:02d}:{t.minute:02d}" for t in parsed_times])
            yield event.plain_result(f"已设置定时广告发送时间：{times_str}")
        else:
            yield event.plain_result("定时广告已取消")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("停止广告")
    async def stop_scheduled_advertisement(self, event: AiocqhttpMessageEvent):
        """停止定时广告发送"""
        if self.broadcast_task and not self.broadcast_task.done():
            self.broadcast_task.cancel()
            self.scheduled_times = []
            yield event.plain_result("已停止定时广告发送")
        else:
            yield event.plain_result("当前没有正在运行的定时广告任务")

    async def _scheduled_broadcast(self):
        """定时广告任务"""
        logger.info("定时广告任务已启动")
        while True:
            try:
                now = datetime.now()
                # 检查是否到达任何一个设定的时间点（分钟级匹配）
                for scheduled_time in self.scheduled_times:
                    if now.hour == scheduled_time.hour and now.minute == scheduled_time.minute:
                        # 如果没有广告内容，则跳过
                        if not self.advertisements:
                            continue
                            
                        # 随机选择一个广告
                        ad = random.choice(self.advertisements)
                        
                        # 获取可广告的群组
                        client = self.context.platform_manager.get_platform_instance("aiocqhttp").bot
                        able_gids = await self.get_able_gids(client)
                        if not able_gids:
                            continue

                        # 向所有启用的群组发送广告
                        success_count = 0
                        failure_count = 0
                        for gid in able_gids:
                            await asyncio.sleep(random.randint(1, 3))  # 控制发送间隔
                            try:
                                await client.send_group_msg(
                                    group_id=int(gid), message=ad["content"]
                                )
                                success_count += 1
                            except Exception as e:
                                failure_count += 1
                                logger.error(f"向群组 {gid} 发送广告失败: {e}")
                                
                        logger.info(f"定时广告发送完成 - 成功: {success_count}个群, 失败: {failure_count}个群")
                
                # 等待到下一分钟
                await asyncio.sleep(60 - now.second)
            except asyncio.CancelledError:
                logger.info("定时广告任务已取消")
                break
            except Exception as e:
                logger.error(f"定时广告任务出错: {e}")
                await asyncio.sleep(60)  # 出错时等待1分钟后继续

    async def terminate(self):
        """插件卸载时停止定时任务"""
        if self.broadcast_task and not self.broadcast_task.done():
            self.broadcast_task.cancel()