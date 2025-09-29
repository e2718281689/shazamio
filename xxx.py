import asyncio
import aiohttp
import webbrowser
import platform
import os
import re
from shazamio import Shazam
import musicbrainzngs

# --- MusicBrainz API 配置 ---
musicbrainzngs.set_useragent(
    "MusicCoverFinder",
    "2.2", # 修复下载逻辑
    "mailto:your-email@example.com",
)

# [关键修改] 函数：正确处理重定向并验证内容类型
async def download_cover(url, save_path):
    """
    异步下载单张封面图片，正确处理重定向并验证文件类型。
    """
    if not url: return False
    print(f"  -> 正在下载: {url}")
    try:
        headers = {'User-Agent': 'Mozilla/so.0'}
        async with aiohttp.ClientSession(headers=headers) as session:
            # 步骤 1: 移除 allow_redirects=False，允许客户端自动跟随跳转
            async with session.get(url, timeout=30) as response:
                
                # 步骤 2: 检查最终响应的状态码
                if response.status == 200:
                    
                    # 步骤 3: 检查最终响应的内容是不是图片
                    content_type = response.headers.get('Content-Type', '').lower()
                    if 'image' in content_type:
                        with open(save_path, 'wb') as f:
                            f.write(await response.read())
                        print(f"     成功下载并保存图片到: {os.path.abspath(save_path)}")
                        return True
                    else:
                        print(f"     下载成功，但文件不是图片 (类型: {content_type})。可能是一个 '未找到' 页面。")
                        return False
                else:
                    # 如果最终状态不是 200 OK，说明跳转后也失败了
                    print(f"     下载失败，最终服务器返回状态码: {response.status}")
                    return False

    except asyncio.TimeoutError:
        print("     下载超时。")
        return False
    except Exception as e:
        print(f"     下载时发生错误: {e}")
        return False

def find_japanese_name_from_romaji(romaji_name):
    print(f"--- 正在 MusicBrainz 中通用搜索: '{romaji_name}' ---")
    try:
        result = musicbrainzngs.search_artists(query=romaji_name.lower(), limit=5)
        artist_list = result.get('artist-list', [])
        if not artist_list:
            print(f"    -> 未找到任何相关艺术家。")
            return None
        for artist in artist_list:
            main_name = artist.get('name', '').lower()
            sort_name = artist.get('sort-name', '').lower()
            if ',' in sort_name:
                parts = [p.strip() for p in sort_name.split(',')]
                formatted_sort_name = f"{parts[1]} {parts[0]}"
            else:
                formatted_sort_name = sort_name
            aliases = {alias.get('alias', '').lower() for alias in artist.get('alias-list', [])}
            if (romaji_name.lower() == main_name or 
                romaji_name.lower() == formatted_sort_name or 
                romaji_name.lower() in aliases):
                official_name = artist['name']
                print(f"    -> 成功匹配！ 罗马音 '{romaji_name}' 对应日文名: {official_name}")
                return official_name
        print(f"    -> 虽找到相似艺术家，但无一精确匹配。")
        return None
    except musicbrainzngs.WebServiceError as e:
        print(f"    -> 查询时出错: {e}")
        return None

def build_comprehensive_keyword_list(shazam_artist):
    print(f"\n--- 正在为 '{shazam_artist}' 构建关键词列表 ---")
    keywords = set()
    base_romaji_names = {shazam_artist.lower()}
    match = re.match(r'^(.*)\s\(CV:\s(.*?)\)$', shazam_artist, re.IGNORECASE)
    if match:
        character_name = match.group(1).strip()
        va_name = match.group(2).strip()
        if character_name: base_romaji_names.add(character_name.lower())
        if va_name: base_romaji_names.add(va_name.lower())
    keywords.update(base_romaji_names)
    for name in base_romaji_names:
        japanese_name = find_japanese_name_from_romaji(name)
        if japanese_name:
            keywords.add(japanese_name.lower())
    final_list = list(keywords)
    print(f"\n最终生成的关键词列表: {final_list}")
    return final_list

def get_all_covers_from_musicbrainz(artist_keywords, shazam_title):
    print(f"\n--- 正在 MusicBrainz 中使用关键词搜索歌曲 '{shazam_title}' ---")
    cover_urls = set()
    try:
        result = musicbrainzngs.search_recordings(recording=shazam_title, limit=25)
        recordings = result.get('recording-list', [])
        if not recordings:
            print("在 MusicBrainz 中未找到与该歌曲名匹配的任何录音。")
            return []
        print(f"在 MusicBrainz 中找到 {len(recordings)} 个同名录音，现在开始用关键词列表进行匹配...")
        filtered_count = 0
        for recording in recordings:
            artist_credits = recording.get('artist-credit', [])
            match_found = False
            for credit in artist_credits:
                if not isinstance(credit, dict): continue
                artist_info = credit.get('artist', {})
                musicbrainz_artist_names = set()
                main_name = artist_info.get('name')
                if main_name: musicbrainz_artist_names.add(main_name.lower())
                aliases = artist_info.get('alias-list', [])
                for alias in aliases:
                    alias_name = alias.get('alias')
                    if alias_name: musicbrainz_artist_names.add(alias_name.lower())
                if not set(artist_keywords).isdisjoint(musicbrainz_artist_names):
                    match_found = True
                    break
            if match_found:
                filtered_count += 1
                if 'release-list' in recording:
                    for release in recording['release-list']:
                        release_id = release['id']
                        cover_url = f"https://coverartarchive.org/release/{release_id}/front"
                        cover_urls.add(cover_url)
        if filtered_count == 0:
            print(f"警告: 未能将任何录音与给定的艺术家关键词匹配上。")
        else:
            print(f"筛选完成！有 {filtered_count} 个录音匹配成功，共找到 {len(cover_urls)} 个不重复的潜在封面。")
        return list(cover_urls)
    except musicbrainzngs.WebServiceError as exc:
        print(f"连接 MusicBrainz API 时出错: {exc}"); return []
    except Exception as e:
        import traceback
        print(f"处理 MusicBrainz 数据时发生未知错误: {e}"); traceback.print_exc(); return []

async def main():
    shazam = Shazam()
    file_path = "01_02_Coffret Comet_城ヶ崎莉嘉(CV_山本希望).wav"
    if not os.path.exists(file_path):
        print(f"错误: 文件 '{file_path}' 不存在。"); return
    print(f"--- 步骤 1: 正在使用 Shazam 识别歌曲 ---"); print(f"文件: {file_path}")
    out = await shazam.recognize(file_path)
    if not (out and out.get('track')):
        print("\n--- Shazam 识别失败 ---"); return
    track_info = out['track']
    title = track_info.get('title', '未知歌曲')
    subtitle = track_info.get('subtitle', '未知艺术家')
    print("\n--- Shazam 识别成功 ---"); print(f"歌曲名: {title}"); print(f"艺术家: {subtitle}")
    artist_keywords = build_comprehensive_keyword_list(subtitle)
    all_cover_urls = get_all_covers_from_musicbrainz(artist_keywords, title)
    if not all_cover_urls:
        print("未能找到该艺术家的任何相关封面。"); return
    print("\n--- 步骤 3: 开始下载所有封面 ---")
    downloaded_files = []
    base_filename = f"{title} - {subtitle}".replace('/', '_').replace('\\', '_').replace(':', '_').replace('?', '').replace('*', '')
    output_dir = f"./{base_filename}_covers"
    os.makedirs(output_dir, exist_ok=True)
    print(f"封面将保存到目录: {os.path.abspath(output_dir)}")
    tasks = [asyncio.create_task(download_cover(url, os.path.join(output_dir, f"cover_{i+1}.jpg"))) for i, url in enumerate(all_cover_urls)]
    results = await asyncio.gather(*tasks)
    for i, success in enumerate(results):
        if success: downloaded_files.append(os.path.join(output_dir, f"cover_{i+1}.jpg"))
    print("\n--- 下载完成 ---")
    if downloaded_files:
        print(f"共成功下载 {len(downloaded_files)} 张封面。"); print("正在尝试打开第一张封面作为预览...")
        open_image(downloaded_files[0])
    else:
        print("虽然找到了封面的链接，但未能成功下载任何一张。")

def open_image(file_path):
    try:
        abs_path = os.path.abspath(file_path)
        if platform.system() == 'Darwin': os.system(f'open "{abs_path}"')
        elif platform.system() == 'Windows': os.startfile(abs_path)
        else: os.system(f'xdg-open "{abs_path}"')
    except Exception as e: print(f"无法自动打开图片，请手动查看。错误: {e}")


if __name__ == "__main__":
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
