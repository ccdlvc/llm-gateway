"""Setup script for LLM Gateway."""

from setuptools import setup, find_packages


setup(
    name="llm-gateway",
    version="0.1.0",
    author="Your Name",
    description=(
        "LLM Account Gateway - Balance-aware routing for multi-account Claude usage. "
        "Routes requests across multiple Anthropic accounts based on remaining balance, "
        "weighting, health status, and latency."
    ),
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "flask>=2.3.0",
        "flask-cors>=4.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "black>=23.0.0",
            "ruff>=0.1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "llm-gateway=__main__:main",
        ],
    },
)
