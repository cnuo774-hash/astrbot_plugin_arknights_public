import astrbot.api.message_components as Comp
from astrbot.api.event.filter import command
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Image
import aiohttp
import asyncio
import datetime

class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.session = aiohttp.ClientSession()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; AstrBotPlugin/1.0)"
        })
        # 缓存游戏数据
        self._char_cache = None
        self._item_cache = None
        self._name_to_id = {}  # 初始化为字典

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        await self._load_name_mapping()

    async def _load_name_mapping(self):
        """加载中文名到游戏 ID 的映射"""
        try:
            url = "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/character_table.json"
            logger.info(f"正在从 GitHub 加载干员数据：{url}")
            
            async with self.session.get(url, timeout=15) as r:
                logger.debug(f"HTTP 状态码：{r.status}")
                if r.status != 200:
                    logger.error(f"HTTP 错误：{r.status}")
                    self._name_to_id = {}
                    return
                    
                text = await r.text()
                logger.debug(f"响应大小：{len(text)} 字节")
                
                try:
                    data = await r.json()
                except Exception as json_err:
                    logger.error(f"JSON 解析失败：{json_err}")
                    logger.error(f"响应内容前 200 字符：{text[:200]}")
                    self._name_to_id = {}
                    return
    
            count = 0
            for char_id, info in data.items():
                if "name" in info:
                    self._name_to_id[info["name"]] = {
                        "id": char_id,
                        "rarity": info.get("rarity", 0),
                        "profession": info.get("profession", "未知")
                    }
                    count += 1
                    
            logger.info(f"成功加载 {count} 个干员数据")
        except asyncio.TimeoutError:
            logger.error("加载干员数据超时 (15 秒)，请检查网络连接")
            self._name_to_id = {}
        except aiohttp.ClientError as e:
            logger.error(f"网络请求失败：{type(e).__name__}: {e}")
            logger.error("请检查是否能访问 GitHub Raw (raw.githubusercontent.com)")
            self._name_to_id = {}
        except Exception as e:
            logger.error(f"加载干员数据失败：{type(e).__name__}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self._name_to_id = {}

    async def github_get_game_data(self, filename: str):
        """获取 GitHub 公开游戏数据"""
        url = f"https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/{filename}"
        try:
            logger.debug(f"请求游戏数据：{url}")
            async with self.session.get(url, timeout=15) as r:
                if r.status != 200:
                    logger.error(f"HTTP 错误 {r.status}: {url}")
                    return None
                return await r.json()
        except asyncio.TimeoutError:
            logger.error(f"获取 {filename} 超时")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"网络请求失败 {filename}: {type(e).__name__}: {e}")
            return None
        except Exception as e:
            logger.error(f"获取游戏数据失败 {filename}: {type(e).__name__}: {e}")
            return None

    @command("#查询干员")
    async def query_operator(self, event: AstrMessageEvent, name: str=""):
        """查询干员"""
        if not name:
            yield event.plain_result("请输入干员名称，如：#查询干员 阿米娅")
            return
        
        # 获取干员数据
        chars = await self.github_get_game_data("character_table.json")
        if not chars:
            yield event.plain_result("获取数据失败，请稍后重试")
            return
        
        # 搜索匹配
        matches = []
        for char_id, data in chars.items():
            if name in data.get("name", ""):
                char_info = self._name_to_id.get(data.get("name"), {})
                matches.append({
                    "name": data.get("name"),
                    "rarity": "★" * (data.get("rarity", 0) + 1),
                    "profession": self._translate_profession(data.get("profession", "未知")),
                    "description": data.get("itemDesc", "无描述")[:100] if data.get("itemDesc") else "无描述",
                    "game_id": char_info.get("id", char_id)
                })

        if not matches:
            yield event.plain_result(f"未找到名为「{name}」的干员")
            return

        result = ""
        for m in matches[:1]:  # 限制显示数量
            result += f"【{m['name']}】{m['rarity']}\n"
            result += f"职业：{m['profession']}\n"
            result += f"简介：{m['description']}\n\n"
        
        # 如果有匹配，发送结果和图片
        if matches:
            first_match = matches[0]
            image_url = f"https://prts.wiki/images/立绘_{first_match['game_id']}_2.png"
            try:
                chain = [
                    Comp.Plain(result.strip()),
                    Comp.Image.fromURL(image_url)
                ]
                yield event.chain_result(chain)
            except Exception as e:
                logger.warning(f"加载图片失败：{e}，仅发送文本信息")
                yield event.plain_result(result.strip())

    def _translate_profession(self, profession: str) -> str:
        """翻译职业名称"""
        profession_map = {
            "WARRIOR": "近卫",
            "SNIPER": "狙击",
            "CASTER": "术师",
            "TANK": "重装",
            "SUPPORT": "辅助",
            "MEDIC": "医疗",
            "SPECIAL": "特种",
            "PIONEER": "先锋"
        }
        return profession_map.get(profession, profession or "未知")

    @command("#今日素材")
    async def get_today_farming(self, event: AstrMessageEvent):
        '''获取今日开放关卡（公开数据推算）'''
        # 根据星期几推算开放关卡
        weekday = datetime.datetime.now().weekday()

        # 关卡开放规律（公开知识）
        schedule = {
            0: "战术演习（经验本）+ 资源保障（龙门币）",
            1: "固若金汤（重装/医疗芯片）+ 摧枯拉朽（狙击/术师芯片）",
            2: "势不可挡（近卫/特种芯片）+ 身先士卒（先锋/辅助芯片）",
            3: "战术演习 + 资源保障",
            4: "固若金汤 + 摧枯拉朽",
            5: "势不可挡 + 身先士卒",
            6: "全部开放"
        }

        today = schedule.get(weekday, "未知")
        result = f"今日（星期{weekday + 1}）开放关卡：\n{today}\n\n"

        yield event.plain_result(result)



    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        logger.info("明日方舟公开数据插件已卸载")
