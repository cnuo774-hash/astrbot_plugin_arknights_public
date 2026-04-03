import astrbot.api.message_components as Comp
from astrbot.api.event.filter import command, regex
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Image
import aiohttp
import asyncio
import datetime
import json
import re

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
        self._skills_cache = {}  # 缓存技能数据：{char_id: [skill_info, ...]}

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        await self._load_name_mapping()
        # 预加载技能数据到缓存
        await self._preload_skills()

    async def _load_name_mapping(self):
        """加载中文名到游戏 ID 的映射"""
        try:
            url = "https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata/excel/character_table.json"
            logger.info(f"正在从 GitHub 加载干员数据：{url}")
            
            # 增加超时时间和重试机制
            max_retries = 3
            retry_delay = 5  # 秒
            
            for attempt in range(max_retries):
                try:
                    # 使用更长的超时时间 (60 秒)
                    async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as r:
                        logger.debug(f"HTTP 状态码：{r.status} (尝试 {attempt + 1}/{max_retries})")
                        if r.status != 200:
                            logger.error(f"HTTP 错误：{r.status}")
                            if attempt < max_retries - 1:
                                logger.info(f"等待 {retry_delay} 秒后重试...")
                                await asyncio.sleep(retry_delay)
                                continue
                            self._name_to_id = {}
                            return
                            
                        text = await r.text()
                        logger.debug(f"响应大小：{len(text)} 字节")
                        
                        # 手动解析 JSON，避免 MIME 类型问题
                        try:
                            data = json.loads(text)
                        except Exception as json_err:
                            logger.error(f"JSON 解析失败：{json_err}")
                            logger.error(f"响应内容前 200 字符：{text[:200]}")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay)
                                continue
                            self._name_to_id = {}
                            return
                    
                        # 成功获取数据
                        count = 0
                        for char_id, info in data.items():
                            if "name" in info:
                                # 在加载缓存时就转换稀有度字段
                                rarity_num = self._convert_rarity(info.get("rarity", 0))
                                self._name_to_id[info["name"]] = {
                                    "id": char_id,
                                    "rarity": rarity_num,  # 存储转换后的整数
                                    "profession": info.get("profession", "未知")
                                }
                                count += 1
                                
                        logger.info(f"成功加载 {count} 个干员数据")
                        return  # 成功后退出
                        
                except asyncio.TimeoutError:
                    logger.warning(f"加载干员数据超时 (尝试 {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        logger.info(f"等待 {retry_delay} 秒后重试...")
                        await asyncio.sleep(retry_delay)
                    else:
                        logger.error("加载干员数据超时 (60 秒)，请检查网络连接")
                        self._name_to_id = {}
                        return
                except aiohttp.ClientError as e:
                    logger.warning(f"网络请求失败：{type(e).__name__}: {e} (尝试 {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        logger.info(f"等待 {retry_delay} 秒后重试...")
                        await asyncio.sleep(retry_delay)
                    else:
                        logger.error(f"网络请求失败：{type(e).__name__}: {e}")
                        logger.error("请检查是否能访问 GitHub Raw (raw.githubusercontent.com)")
                        self._name_to_id = {}
                        return

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
            # 增加超时时间和重试机制
            max_retries = 3
            retry_delay = 5
            
            for attempt in range(max_retries):
                try:
                    # 使用更长的超时时间 (60 秒)
                    async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as r:
                        if r.status != 200:
                            logger.error(f"HTTP 错误 {r.status}: {url} (尝试 {attempt + 1}/{max_retries})")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay)
                                continue
                            return None
                        
                        # 获取文本并手动解析 JSON
                        text = await r.text()
                        try:
                            return json.loads(text)
                        except Exception as json_err:
                            logger.error(f"JSON 解析失败 {filename}: {json_err}")
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay)
                                continue
                            return None
                except asyncio.TimeoutError:
                    logger.warning(f"获取 {filename} 超时 (尝试 {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                    else:
                        logger.error(f"获取 {filename} 超时")
                        return None
                except aiohttp.ClientError as e:
                    logger.warning(f"网络请求失败 {filename}: {type(e).__name__}: {e} (尝试 {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                    else:
                        logger.error(f"网络请求失败 {filename}: {type(e).__name__}: {e}")
                        return None
                        
            return None
        except Exception as e:
            logger.error(f"获取游戏数据失败 {filename}: {type(e).__name__}: {e}")
            return None

    @command("查询干员")
    @regex(r"/?查询干员\s*(.*)")
    async def query_operator(self, event: AstrMessageEvent, name: str=""):
        """查询干员"""
        # 从正则匹配中获取参数
        message_str = event.get_message_str().strip()
        match = re.search(r"/?查询干员\s*(.*)", message_str)
        if match:
            name = match.group(1).strip()
        
        if not name:
            yield event.plain_result("请输入干员名称，如：#查询干员 阿米娅")
            return
        
        # 优先使用缓存的数据进行查询
        if not self._name_to_id:
            # 如果缓存为空，尝试从 GitHub 加载
            logger.info("缓存为空，正在加载干员数据...")
            chars = await self.github_get_game_data("character_table.json")
            if not chars:
                yield event.plain_result("获取数据失败，请稍后重试")
                return
            
            # 更新缓存
            count = 0
            for char_id, info in chars.items():
                if "name" in info:
                    rarity_num = self._convert_rarity(info.get("rarity", 0))
                    self._name_to_id[info["name"]] = {
                        "id": char_id,
                        "rarity": rarity_num,
                        "profession": info.get("profession", "未知")
                    }
                    count += 1
            logger.info(f"成功加载 {count} 个干员数据到缓存")
        
        # 在缓存中搜索匹配
        matches = []
        for char_name, info in self._name_to_id.items():
            if name in char_name:
                rarity_num = info.get("rarity", 0)
                # rarity_num 应该已经是整数了，因为缓存时已经转换过
                matches.append({
                    "name": char_name,
                    "rarity": "★" * (rarity_num + 1),
                    "profession": self._translate_profession(info.get("profession", "未知")),
                    "game_id": info.get("id", ""),
                    "rarity_num": rarity_num  # 用于后续技能查询
                })

        if not matches:
            yield event.plain_result(f"未找到名为「{name}」的干员")
            return

        result = ""
        for m in matches[:1]:  # 限制显示数量
            result += f"【{m['name']}】{m['rarity']}\n"
            result += f"职业：{m['profession']}\n"
            result += f"ID: {m['game_id']}\n\n"
            
            # 从缓存获取技能描述（无需网络请求）
            skill_desc = self._get_cached_skills(m['game_id'], m['name'])
            if skill_desc:
                result += skill_desc
        
        # 如果有匹配，发送结果和图片
        if matches:
            first_match = matches[0]
            game_id = first_match['game_id']
            
            # 尝试多个图片源 (使用更可靠的源，调整顺序和超时时间)
            image_urls = [
                f"https://prts.wiki/images/立绘_{game_id}_2.png",  # PRTS Wiki (较稳定)
                f"https://cdn.jsdelivr.net/gh/yuanyan3060/ArknightsGameResource@main/character/{game_id}/icon.png",  # JSDELivr 镜像
                f"https://fastly.jsdelivr.net/gh/yuanyan3060/ArknightsGameResource@main/character/{game_id}/icon.png",  # Fastly CDN
                f"https://raw.githubusercontent.com/yuanyan3060/ArknightsGameResource/main/character/{game_id}/icon.png",
                f"https://ak.hypergryph.com/assets/media/characters/{game_id}.png",  # 官服源 (可能限制访问)
            ]
            
            # 如果所有图片源都失败，准备备用文本结果
            text_only_result = result.strip()
            
            # 尝试发送带图片的消息
            success = False
            for img_url in image_urls:
                try:
                    logger.debug(f"尝试加载图片：{img_url}")
                    # 先验证图片 URL 是否可访问
                    async with self.session.get(img_url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                        if r.status == 200:
                            content_type = r.headers.get('Content-Type', '')
                            # 检查是否为图片类型或内容长度合理
                            content_length = int(r.headers.get('Content-Length', 0))
                            logger.debug(f"图片源响应 {img_url}: HTTP {r.status}, Content-Type: {content_type}, Length: {content_length}")
                            if ('image' in content_type or content_length > 1000) and content_length < 10 * 1024 * 1024:
                                chain = [
                                    Comp.Plain(text_only_result),
                                    Comp.Image.fromURL(img_url)
                                ]
                                yield event.chain_result(chain)
                                success = True
                                return  # 成功后直接返回
                            else:
                                logger.debug(f"图片源无效 {img_url}: Content-Type: {content_type}, Length: {content_length}")
                                continue
                        else:
                            logger.debug(f"图片源返回错误 {img_url}: HTTP {r.status}")
                            continue
                except asyncio.TimeoutError:
                    logger.debug(f"图片源超时 {img_url} (10 秒)")
                    continue
                except aiohttp.ClientError as e:
                    logger.debug(f"图片源请求失败 {img_url}: {type(e).__name__}: {e}")
                    continue
                except Exception as e:
                    logger.debug(f"图片源失败 {img_url}: {type(e).__name__}: {e}")
                    continue
            
            # 所有图片源都失败，只发送文本
            if not success:
                logger.warning("所有图片源加载失败，仅发送文本信息")
                yield event.plain_result(text_only_result)

    def _convert_rarity(self, rarity_value):
        """转换稀有度字段为数字
        
        Args:
            rarity_value: 可能是数字或 TIER_X 格式的字符串
            
        Returns:
            int: 稀有度数字
        """
        if isinstance(rarity_value, int):
            return rarity_value
        if isinstance(rarity_value, str):
            # 处理 TIER_0, TIER_1, TIER_2 等格式
            if rarity_value.startswith("TIER_"):
                try:
                    return int(rarity_value.split("_")[1])
                except (IndexError, ValueError):
                    logger.warning(f"无法解析稀有度：{rarity_value}")
                    return 0
            # 尝试直接转换为数字
            try:
                return int(rarity_value)
            except ValueError:
                logger.warning(f"无法转换稀有度：{rarity_value}")
                return 0
        return 0

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

    async def _preload_skills(self):
        """预加载技能数据到缓存"""
        try:
            logger.info("正在预加载技能数据...")
            skills_data = await self.github_get_game_data("skill_table.json")
            if not skills_data:
                logger.warning("技能数据加载失败")
                return
            
            logger.info(f"技能数据总数：{len(skills_data)}")
            
            # 先加载干员数据来建立英文名到 char_id 的映射
            chars_data = await self.github_get_game_data("character_table.json")
            if not chars_data:
                logger.warning("无法加载干员数据，技能解析可能不完整")
                chars_data = {}
            
            # 建立英文名到 char_id 的映射
            en_name_to_char_id = {}
            for char_id, info in chars_data.items():
                if "name" in info:
                    en_name = info["name"]
                    # 存储多个版本：原名、小写、去除空格等
                    en_name_lower = en_name.lower()
                    en_name_no_space = en_name.replace(" ", "").lower()
                    
                    # 原始名称
                    en_name_to_char_id[en_name_lower] = char_id
                    # 不带空格
                    en_name_to_char_id[en_name_no_space] = char_id
                    # 去掉括号内容（如果有）
                    if '(' in en_name:
                        base_name = en_name.split('(')[0].strip().lower()
                        en_name_to_char_id[base_name] = char_id
                        en_name_to_char_id[base_name.replace(" ", "")] = char_id
            
            logger.info(f"建立了 {len(en_name_to_char_id)} 个干员英文名到 ID 的映射")
            
            # 调试：打印阿米娅相关的映射
            amiya_mappings = {k: v for k, v in en_name_to_char_id.items() if 'amiya' in k}
            if amiya_mappings:
                logger.info(f"阿米娅的映射：{amiya_mappings}")
            
            # 预处理技能数据，建立 char_id 到技能的映射
            count = 0
            failed_count = 0
            debug_count = 0  # 调试计数器
            
            # 打印前几个技能 ID 来帮助调试
            for i, (skill_id, skill_info) in enumerate(skills_data.items()):
                if i < 3:  # 只打印前 3 个
                    logger.info(f"示例技能 ID[{i}]: {skill_id}")
            
            # 搜索阿米娅的技能来帮助调试
            amiya_skills = [sid for sid in skills_data.keys() if 'amiya' in sid.lower()]
            if amiya_skills:
                logger.info(f"找到阿米娅的技能 ID: {amiya_skills[:5]}")  # 最多显示 5 个
            
            # 分析技能 ID 格式，帮助调试
            skill_formats = {}
            for skill_id in list(skills_data.keys())[:20]:
                if skill_id.startswith('skchr_'):
                    skill_formats[skill_id] = 'skchr_'
                elif skill_id.startswith('skcom_'):
                    skill_formats[skill_id] = 'skcom_'
                elif '[' in skill_id:
                    skill_formats[skill_id] = 'with_brackets'
                else:
                    skill_formats[skill_id] = 'other'
            logger.info(f"技能 ID 格式示例：{skill_formats}")
            
            for skill_id, skill_info in skills_data.items():
                # 提取技能 ID 中的干员 ID 部分
                # 技能 ID 格式：skchr_amiya_2, skchr_amiya2_1, char_002_amiya_skill_01 等
                char_id = None
                
                # 尝试多种匹配模式
                if skill_id.startswith("skchr_"):
                    # 格式：skchr_amiya_2, skchr_amiya2_1, skchr_blackd_1
                    # 提取干员英文名部分
                    match = re.search(r'skchr_([^_]+)_\d+', skill_id)
                    if match:
                        char_en_name = match.group(1).lower()  # 如：amiya, amiya2, blackd
                        logger.debug(f"技能 {skill_id} 提取出英文名：{char_en_name}")
                        
                        # 在映射表中查找 - 精确匹配
                        if char_en_name in en_name_to_char_id:
                            char_id = en_name_to_char_id[char_en_name]
                            logger.debug(f"✓ 精确匹配成功：{char_en_name} -> {char_id}")
                        else:
                            # 尝试去掉末尾数字
                            base_name = re.sub(r'\d+$', '', char_en_name)
                            logger.debug(f"尝试模糊匹配基名：{base_name}")
                            
                            # 方法 1：直接匹配基名
                            if base_name in en_name_to_char_id:
                                char_id = en_name_to_char_id[base_name]
                                logger.debug(f"✓ 基名匹配成功：{base_name} -> {char_id}")
                            else:
                                # 方法 2：遍历查找包含关系
                                for name, cid in en_name_to_char_id.items():
                                    # 检查映射名是否以基名开头或包含基名
                                    if name.startswith(base_name) or base_name in name:
                                        char_id = cid
                                        logger.debug(f"✓ 包含匹配成功：{base_name} in {name} -> {char_id}")
                                        break
                                    # 检查是否只是数字差异
                                    name_base = re.sub(r'\d+$', '', name)
                                    if name_base == base_name and len(name_base) > 2:
                                        char_id = cid
                                        logger.debug(f"✓ 去数字匹配成功：{name} -> {char_id}")
                                        break
                        
                        if not char_id:
                            logger.debug(f"✗ 无法匹配：{char_en_name}")
                            # 特殊处理：如果是 amiya2/amiya3，尝试匹配 amiya
                            if 'amiya' in char_en_name:
                                if 'amiya' in en_name_to_char_id:
                                    char_id = en_name_to_char_id['amiya']
                                    logger.debug(f"✓ 特殊匹配阿米娅：amiya -> {char_id}")
                elif skill_id.startswith("skcom_"):
                    # 通用技能，跳过
                    continue
                elif "[" in skill_id and "]" in skill_id:
                    # 格式：skcom_charge_cost[1], skcom_assist_cost[2] 等
                    # 这些可能是通用技能，不是特定干员的技能
                    match = re.search(r'^([^\[]+)\[', skill_id)
                    if match:
                        base_id = match.group(1)
                        # 检查是否包含 char 字样
                        char_match = re.search(r'(char_[^_]+_[^_]+)', base_id)
                        if char_match:
                            char_id = char_match.group(1)
                        else:
                            # 跳过通用技能
                            continue
                elif skill_id.startswith("skill_"):
                    # 格式：skill_char_002_amiya 或 skill_002_amiya
                    match = re.search(r'skill_(char_[a-zA-Z0-9_]+)', skill_id)
                    if match:
                        char_id = match.group(1)
                elif "_char_" in skill_id:
                    parts = skill_id.split("_char_")
                    if len(parts) > 1:
                        # 提取 char_xxx 部分
                        remainder = parts[1]
                        match = re.match(r'(char_[^_]+)', remainder)
                        if match:
                            char_id = match.group(1)
                elif skill_id.startswith("char_") and "_skill_" in skill_id:
                    # 格式：char_002_amiya_skill_01
                    parts = skill_id.split("_skill_")
                    if parts:
                        char_id = parts[0]
                else:
                    # 尝试从 skill_info 中查找 char_id
                    # 有些技能可能直接关联到干员 ID
                    char_id_match = re.search(r'(char_[^_\s]+)', skill_id)
                    if char_id_match:
                        char_id = char_id_match.group(1)
                
                # 如果还是找不到，打印调试信息
                if not char_id:
                    if failed_count < 5:  # 只打印前 5 个失败的
                        logger.warning(f"无法提取干员 ID: skill_id={skill_id}")
                        failed_count += 1
                    continue
                
                if char_id:
                    if char_id not in self._skills_cache:
                        self._skills_cache[char_id] = []
                    
                    # 解析技能信息
                    skill_name = skill_info.get("name", "未知")
                    desc = skill_info.get("description", "")
                    if not desc:
                        desc = skill_info.get("description_override", "暂无描述")
                    
                    # 获取满级描述
                    levels = skill_info.get("levels", [])
                    if levels and len(levels) > 0:
                        last_level = levels[-1]
                        desc_override = last_level.get("description_override", desc)
                        if desc_override:
                            desc = desc_override
                    
                    self._skills_cache[char_id].append({
                        "name": skill_name,
                        "desc": desc
                    })
                    count += 1
                    
                    # 打印前 10 个调试信息
                    if debug_count < 10:
                        logger.debug(f"技能 ID: {skill_id} -> 干员 ID: {char_id}, 技能名：{skill_name}")
                        debug_count += 1
            
            logger.info(f"成功预加载 {len(self._skills_cache)} 个干员的技能数据 (共处理 {count} 个技能，失败 {failed_count} 个)")
            
            # 调试：检查阿米娅的技能是否在缓存中
            if 'char_002_amiya' in self._skills_cache:
                logger.info(f"✓ 阿米娅的技能已缓存：{len(self._skills_cache['char_002_amiya'])} 个技能")
            else:
                logger.warning("✗ 阿米娅的技能未找到缓存")
                logger.warning("提示：skchr_amiya_* 格式的技能需要建立英文名到 char_id 的映射")
        except Exception as e:
            logger.error(f"预加载技能数据失败：{type(e).__name__}: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def _get_cached_skills(self, char_id: str, char_name: str) -> str:
        """从缓存获取干员技能描述（无需网络请求）"""
        try:
            if char_id not in self._skills_cache or not self._skills_cache[char_id]:
                return ""
            
            operator_skills = []
            for skill_info in self._skills_cache[char_id]:
                skill_name = skill_info.get("name", "未知")
                desc = skill_info.get("desc", "暂无描述")
                operator_skills.append(f"技能：{skill_name}\n{desc}\n")
            
            if operator_skills:
                return "\n".join(operator_skills[:3]) + "\n"  # 最多显示 3 个技能
            return ""
        except Exception as e:
            logger.error(f"读取技能缓存失败 {char_name}: {type(e).__name__}: {e}")
            return ""

    @command("今日素材")
    @regex(r"/?今日素材$")
    async def get_today_farming(self, event: AstrMessageEvent):
        '''获取今日开放关卡（公开数据推算）'''
        # 根据星期几推算开放关卡
        weekday = datetime.datetime.now().weekday()

        # 关卡开放规律（公开知识）
        schedule = {
            0: "基建材料 + 红票 + 重装/医疗芯片 + 狙击/术师芯片",
            1: "龙门币 + 技能材料 + 狙击/术师芯片 + 近卫/特种芯片",
            2: "基建材料 + 技能材料 + 先锋/辅助芯片 + 近卫/特种芯片 ）",
            3: "龙门币 + 红票 + 重装/医疗芯片 + 先锋/辅助芯片",
            4: "基建材料 + 技能材料 + 狙击/术师芯片 + 重装/医疗芯片",
            5: "龙门币 + 基建材料 + 红票 + 先锋/辅助芯片 + 近卫/特种芯片 + 狙击/术师芯片",
            6: "全部开放"
        }

        today = schedule.get(weekday, "未知")
        result = f"今日（星期{weekday + 1}）\n{today}"

        yield event.plain_result(result)



    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        logger.info("明日方舟公开数据插件已卸载")
