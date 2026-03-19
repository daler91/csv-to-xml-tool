with open("src/xml-validator.py", "r") as f:
    content = f.read()

content = content.replace("\nimport os\n\nimport xml.etree.ElementTree as ET", "\nimport os\nimport xml.etree.ElementTree as ET")

with open("src/xml-validator.py", "w") as f:
    f.write(content)
