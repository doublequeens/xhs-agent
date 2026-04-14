import argparse
import sys
import json
from src.graph import create_graph

def main():
    parser = argparse.ArgumentParser(description="Xiaohongshu Agent CLI")
    parser.add_argument("--topic_num", type=int, required=True, help="Topic of the post")
    # parser.add_argument("--requirements", type=str, default="", help="Additional requirements")
    # parser.add_argument("--mode", type=str, default="manual", choices=["auto", "manual"], help="Publishing mode")
    
    args = parser.parse_args()
    
    print(f"Starting Xiaohongshu Agent for topic number: {args.topic_num}")
    
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
    graph = create_graph()

    initial_state = {
        "trends_num": args.topic_num,
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
        "publish_package": None
    }

    # 如果想完全从头重新跑一次，请修改此处的 thread_id（如 "xhs_conversation_2"）
    index = "5_glm"
    config = {"configurable": {"thread_id": "xhs_conversation_"+ str(index)}}

    currentState = graph.get_state(config)
    # print(currentState.values)
    
    # 判断是否已有历史状态，如果有则传入 None 恢复执行，否则传入 initial_state 全新启动
    if currentState.values:
        print("Found existing state, resuming from the latest checkpoint...")
        
        # 如果历史状态已经没有任何需要执行的下一个节点（即已经运行到 END）
        if not currentState.next:
            if currentState.values["publish_package"]:
                print("该任务已经全部执行完毕，直接从历史状态导出 publish_package.json...")
                print("The final publish package title is:")
                print(currentState.values["publish_package"]["publish_package"]["title"])
            
                with open("publish_package_" + str(index) + ".json", "w") as f:
                    json.dump(currentState.values["publish_package"]["publish_package"], f, ensure_ascii=False, indent=4)
                return # 直接退出，不需要再跑 stream
            
        run_input = None
    else:
        print("No existing state found, starting a new run...")
        run_input = initial_state

    # Run the graph
    try:
        for output in graph.stream(run_input, config=config):
            for key, value in output.items():
                print(f"Finished processing node: {key}")
                if key == "assembler":
                    print("Final output from assembler node:")
                    print(value)
                    with open("publish_package_" + str(index) + ".json", "w") as f:
                        json.dump(value["publish_package"]["publish_package"], f, ensure_ascii=False, indent=4)

    except Exception as e:
        print(f"Error running agent: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()