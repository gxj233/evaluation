# -*- coding: utf-8 -*-
import threading

import signal
import json
import random
import ast
import pandas as pd
import re
from typing import Any, Tuple
from contextlib import contextmanager
from langchain_experimental.tools.python.tool import PythonAstREPLTool
from evaluate_code_correction.pytool import format_result, extract_last_df

def read_jsonl(file_path):

    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            data.append(json.loads(line.strip()))
    return data

def load_json(data_path):
    """
    # 加载 json 文件
    """
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def save_json(data_path, data_list):
    """
    # 保存 json 文件
    """
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data_list, f, ensure_ascii=False)
        

def get_dfs_info(table_paths):
    """将所有csv文件对应的df-info拼装到一起"""
    infos_list = []
    if len(table_paths) == 1:
        df_markdown_info = str(pd.read_csv(table_paths[0], encoding="utf-8").head(5).to_string(index=False))
        normalized_head = f"""/*\n"df.head()" as follows:\n{df_markdown_info}\n*/"""
        infos_list.append(normalized_head)
    else:
        for i, path in enumerate(table_paths):
            # normalized_name = normalize_table_name(path)
            df_markdown_info = str(pd.read_csv(path, encoding="utf-8").head(5).to_string(index=False))
            normalized_head = f"""/*\n"df{i+1}.head()" as follows:\n{df_markdown_info}\n*/"""
            # single_table_name = "\n".join([normalized_head, df_markdown_info])
            infos_list.append(normalized_head)
    return "\n".join(infos_list)

def sample_from_two_lists(list1, list2):  
    # 如果列表为空，则直接返回None或抛出异常，取决于你的需求  
    if not list1 or not list2:  
        return None  # 或者你可以抛出异常  
  
    # 生成一个0到1之间的随机浮点数  
    rand_val = random.random()  
  
    # 如果随机数小于0.5，从第一个列表中采样  
    if rand_val < 0.5:  
        return random.choice(list1)  
    # 否则，从第二个列表中采样  
    else:  
        return random.choice(list2)  

def recraft_query(query, locals):
    last_df = extract_last_df(query, locals)
    end_str = "\n" + format_result + "print(format_result({}))".format(last_df)
    recraft_query = query + end_str
    return recraft_query


def extract_code_without_comments(code):
    """
    从Python代码中提取除注释行以外的代码。

    :param code: str, 输入的Python代码
    :return: str, 提取后的代码
    """
    code = re.sub(r'"""[\s\S]*?"""', "", code)
    code = re.sub(r"'''[\s\S]*?'''", "", code)

    # 移除单行注释
    lines = code.split("\n")
    cleaned_lines = []
    for line in lines:
        # 移除以 # 开始的注释，但保留字符串中的 #
        cleaned_line = re.sub(r'(?<!["\'"])#.*$', "", line)
        cleaned_lines.append(cleaned_line.rstrip())  # rstrip() 移除行尾空白
    # 重新组合代码，保留空行以维持原始结构
    return "\n".join(cleaned_lines)


def is_python_code(line: str) -> bool:
    """Tool function to check if a line of text is Python code"""
    try:
        tree = ast.parse(line)
        # Check if the parsed tree has at least one node that represents executable code
        for node in ast.walk(tree):
            if isinstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom, ast.For, ast.While, ast.If, ast.With, ast.Raise, ast.Try)):
                return True
        return False
    except SyntaxError:
        return False


def extract_text_before_code(text: str) -> str:
    """Tool function for extract text content"""
    lines = text.split("\n")
    text_before_code = []

    for line in lines:
        if is_python_code(line):
            break
        text_before_code.append(line)

    return "\n".join(text_before_code)


def extract_python_code(text: str) -> str:
    """Tool function for extract python code"""
    lines = text.split("\n")
    python_code = []

    for line in lines:
        if is_python_code(line):
            python_code.append(line)

    return "\n".join(python_code)


def fix_indents(text: str) -> str:
    return text.replace("\t", "    ")


def filter_cot(completion: str):
    """
    Filter the COT steps before python code
    :param completion: llm output contents
    :return filtered COT content
    """
    try:
        # 如果输出较为规范，可以使用这种方式提取cot部分的内容
        pattern = r"Thought:\s*(.*?)\s*(?=Python Code:)"
        match = re.search(pattern, completion, re.DOTALL)
        if match:
            thought_content = match.group(1)
        else:
            # 如果输出内容相对杂乱
            thought_content = extract_text_before_code(completion)
        return thought_content
    except:
        return ""

def filter_code(completion: str) -> Tuple[str, str]:
    """
    Filter python code from the llm output completion
    :param completion: llm output contents
    :return filtered python code and execute code
    """

    try:
        # 输出形式符合prompt
        regex = r"```python\s(.*?)```"
        action_match = re.search(regex, completion, re.DOTALL)
        if action_match:
            action_input = action_match.group(1)
            action_input = action_input.strip(" ")
            action_input = action_input.strip('"')
            code = action_input.strip(" ")
        else:
            # 输出形式随意
            code = extract_python_code(completion)
            code = code.strip(" ")
        pure_code = extract_code_without_comments(code)
        return code, pure_code
    except:
        return "", ""


def get_tool(df: Any,df_names=None):
    """
    Define python code execute tool
    :param df: List[pd.DataFrame] or pd.DataFrame
    :return Runnable
    """
    tool = PythonAstREPLTool()
    if df_names==None:
        if isinstance(df, pd.DataFrame):
            locals = {"df": df}
        else:
            locals = {}
            for i, dataframe in enumerate(df):
                locals[f"df{i + 1}"] = dataframe
    else:
        locals = {}
        for i, dataframe in enumerate(df):
            locals[df_names[i]] = dataframe
    tool.locals = locals
    tool.globals = tool.locals
    return tool

def get_table_infos(table_paths):
    """将所有csv文件对应的df-info拼装到一起"""
    infos_list = []
    if len(table_paths) == 1:
        df_markdown_info = str(
            pd.read_csv(table_paths[0], encoding="utf-8").head(3).to_markdown(index=False)
        )
        normalized_head = f"""/*\n"df.head()" as follows:\n{df_markdown_info}\n*/"""
        infos_list.append(normalized_head)
    else:
        for i, path in enumerate(table_paths):
            # normalized_name = normalize_table_name(path)
            df_markdown_info = str(
                pd.read_csv(path, encoding="utf-8").head(3).to_markdown(index=False)
            )
            normalized_head = (
                f"""/*\n"df{i+1}.head()" as follows:\n{df_markdown_info}\n*/"""
            )
            # single_table_name = "\n".join([normalized_head, df_markdown_info])
            infos_list.append(normalized_head)
    return "\n".join(infos_list)

# 定义一个异常类，用于超时处理
class TimeoutException(Exception):
    pass


# 创建一个上下文管理器来处理超时
@contextmanager
def timeout(time):
    # 定义信号处理函数
    def raise_timeout(signum, frame):
        raise TimeoutException(f"Timeout error, running time exceed {time}")

    # 设置信号定时器
    signal.signal(signal.SIGALRM, raise_timeout)
    signal.alarm(time)
    try:
        yield
    finally:
        # 取消信号定时器
        signal.alarm(0)


def run_code(code, result, tool):
    try:
        # 在子线程中运行代码
        result.append(tool.run(code))
    except Exception as e:
        result.append(e)


def execute_with_timeout(code, timeout_seconds, tool):
    result = []
    thread = threading.Thread(target=run_code, args=(code, result, tool))
    thread.start()
    thread.join(timeout_seconds)

    if thread.is_alive():
        thread._stop()  # 终止子线程
        raise TimeoutException(
            f"Timeout error, running time exceed {timeout_seconds} seconds"
        )
    else:
        if isinstance(result[0], Exception):
            raise result[0]
        return result[0]
