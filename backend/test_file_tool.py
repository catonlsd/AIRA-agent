from tools.filesystem.file_tool import FileTool


write_result = FileTool.write_file(
    "tmp/aira_x_test.txt",
    "AIRA-X File Tool Working"
)

print("WRITE:", write_result)

read_result = FileTool.read_file("tmp/aira_x_test.txt")

print("READ:", read_result)

list_result = FileTool.list_files("tmp")

print("LIST:", list_result)