import argparse
import os
import sys
import json
from datetime import datetime, timezone, timedelta

from langgraph import graph
from langgraph.types import Command
from memory.memory_manager import XHSMemoryManager
from src.graph import create_graph
from src.models import set_default_provider
from src.prompts import all_prompts


def export_publish_package(publish_package: dict) -> None:
    date_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
    title = publish_package["title"]
    dir_path = "outputs/publish/{post_dir}".format(post_dir=date_str + "-" + title)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    with open(dir_path + "/" + str(title) + ".json", "w") as f:
        json.dump(publish_package, f, ensure_ascii=False, indent=4)

    # 生成供图像生成节点使用的 prompt
    storyboards_image_gen_prompt = all_prompts["NODE_O_STORYBOARDS_IMAGES_GENERATOR"]
    storyboards_image_gen_json = {
        "title": publish_package.get("title", ""),
        "content": publish_package.get("content", ""),
        "cover_copy": publish_package.get("cover_copy", ""),
        "storyboards": publish_package.get("storyboards", [])
        }
    image_prompt = "{image_generating_guide_prompt}\n{storyboards_prompt}\n```".format(image_generating_guide_prompt=storyboards_image_gen_prompt, 
                                                                                       storyboards_prompt=json.dumps(storyboards_image_gen_json, ensure_ascii=False, indent=4))
    with open(dir_path + "/" + "Storyboard_images_generator_prompt.txt", "w") as f:
        f.write(image_prompt)


def read_multiline_json() -> dict:
    print("请粘贴完整 JSON，输入单独一行 END 结束：")
    lines = []
    while True:
        line = input()
        if line.strip() == "END":
            break
        lines.append(line)

    return json.loads("\n".join(lines))


def collect_human_review(interrupt_value: dict) -> dict:
    publish_package = interrupt_value["publish_package"]
    print("\n===== Human Review Required =====")
    print(interrupt_value["message"])
    print(json.dumps(publish_package, ensure_ascii=False, indent=2))

    while True:
        action = input("\n输入 yes 继续；输入 edit 修改 JSON；输入 no 提建议并继续 review: ").strip().lower()

        if action == "yes":
            return {
                "approved": True,
                "edited_publish_package": None,
                "feedback": "approved by user",
            }

        if action == "edit":
            try:
                edited_publish_package = read_multiline_json()
            except json.JSONDecodeError as exc:
                print(f"JSON 解析失败：{exc}")
                continue

            approve = input("修改后是否批准继续？输入 yes 或 no: ").strip().lower()
            feedback = input("可选：补充一点 review 建议，直接回车可跳过: ").strip()
            return {
                "approved": approve == "yes",
                "edited_publish_package": edited_publish_package,
                "feedback": feedback or "edited by user",
            }

        if action == "no":
            feedback = input("请输入 review 建议: ").strip()
            return {
                "approved": False,
                "edited_publish_package": None,
                "feedback": feedback,
            }

        print("无效输入，请输入 yes / edit / no。")


def stream_graph_until_stop(graph, run_input, config):
    next_input = run_input

    while True:
        interrupted = False
        for output in graph.stream(next_input, config=config):
            for key, value in output.items():
                if key == "__interrupt__":
                    interrupted = True
                    interrupt_event = value[0]
                    review_payload = collect_human_review(interrupt_event.value)
                    next_input = Command(resume=review_payload)
                    break

                print(f"Finished processing node: {key}")
                if key in {"storyboard_generator", "human_review"} and value.get("publish_package"):
                    print("The final publish package title is:")
                    print(value["publish_package"]["title"])
                    export_publish_package(value["publish_package"])

            if interrupted:
                break

        if not interrupted:
            return

def main():
    parser = argparse.ArgumentParser(description="Xiaohongshu Agent CLI")
    parser.add_argument("--focus_keyword", type=str,help="Focus keyword for the post")
    parser.add_argument("--topic_num", type=int, required=True, help="Topic of the post")
    parser.add_argument("--provider", type=str, help="Model provider (glm, gemini, deepseek)")
    # parser.add_argument("--requirements", type=str, default="", help="Additional requirements")
    # parser.add_argument("--mode", type=str, default="manual", choices=["auto", "manual"], help="Publishing mode")
    
    args = parser.parse_args()
    
    init_message = f"Starting Xiaohongshu Agent"
    if args.provider:
        init_message += f" with default model: {args.provider},"
    if args.focus_keyword:
        init_message += f" with topic focus keyword: {args.focus_keyword},"
    if args.topic_num:
        init_message += f" with topic number: {args.topic_num}."
    print(init_message)
    
    # 如果用户在启动时指定了 provider，才去修改全局配置，否则保持 __init__.py 里的默认值
    if args.provider:
        set_default_provider(args.provider)

    # # Initialize State
    # initial_state = {
    #     "topic": args.topic,
    #     "requirements": args.requirements,
    #     "revision_count": 0,
    #     "publish_mode": args.mode,
    #     "draft": None,
    #     "critique": None,
    #     "images": [],
    #     "selected_image": None
    # }
    database = XHSMemoryManager("data/xhs_memory.db")
    database.init_db("memory/schema.sql")

    graph = create_graph()

    initial_state = {
        "memory_context": None,
        "trends_num": args.topic_num,
        "focus_keyword": args.focus_keyword if args.focus_keyword else "",
        "trends": [],
        "angles": [],
        "scores": [],
        "outlines": [],
        "drafts": [],
        "title_options": [],
        "title_winner": None,
        "current_node": None,
        "decision_output": None,
        "r1_output": None,
        "r2_output": None,
        "final_content": None,
        "hashtags": None,
        "image_scripts": None,
        "image_candidates": None,
        "final_images": None,
        "publish_package": None,
        "review_status": None,
        "review_feedback": None,
        "review_round": 0,
        "data_writed": None
    }

    # 如果想完全从头重新跑一次，请修改此处的 thread_id（如 "xhs_conversation_2"）
    index = "database_20260509_01"
    config = {"configurable": {"thread_id": "xhs_conversation_"+ str(index)}}

    currentState = graph.get_state(config)
    # print(currentState.values)
    
    # 判断是否已有历史状态，如果有则传入 None 恢复执行，否则传入 initial_state 全新启动
    if currentState.values:
        print("Found existing state, resuming from the latest checkpoint...")
        # history = list(graph.get_state_history(config, limit=2))
        # if len(history) >= 2:
        #     print("The last executed node was:", history[1].values.get("current_node", "Unknown"))
        # else:
        #     print("No previous nodes found in history.")
        
        # 如果历史状态已经没有任何需要执行的下一个节点（即已经运行到 END）
        if not currentState.next:
            if currentState.values["publish_package"]:
                print("该任务已经全部执行完毕，直接从历史状态导出 publish_package.json...")
                print("The final publish package title is:")
                print(currentState.values["publish_package"]["title"])
                export_publish_package(currentState.values["publish_package"])
                return # 直接退出，不需要再跑 stream
            
        run_input = None
    else:
        print("No existing state found, starting a new run...")
        run_input = initial_state

    # Run the graph
    try:
        stream_graph_until_stop(graph, run_input, config)

    except Exception as e:
        print(f"Error running agent: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()