# Rhythms Crew

A powerful multi-agent AI system built with [crewAI](https://crewai.com). This project demonstrates how to orchestrate multiple AI agents to collaborate on complex tasks, leveraging crewAI's flexible framework for maximum efficiency and intelligence.

## Prerequisites

- Python >=3.10 <3.13
- [UV](https://docs.astral.sh/uv/) package manager

## Quick Start

1. Install UV if you haven't already:

```bash
pip install uv
```

2. Clone this repository and navigate to the project directory

3. Install dependencies:

```bash
crewai install
```

4. Set up your environment:

   - Copy `.env.example` to `.env`
   - Add your `OPENAI_API_KEY` to the `.env` file

5. Run the project:

```bash
crewai run
```

By default, this will generate a `report.md` file containing LLM research results.

## Configuration

The project is highly customizable through these key files:

- `src/rhythms/config/agents.yaml` - Define agent roles, capabilities, and behaviors
- `src/rhythms/config/tasks.yaml` - Specify tasks and workflows
- `src/rhythms/crew.py` - Customize logic, tools, and specific arguments
- `src/rhythms/main.py` - Configure custom inputs for agents and tasks

## Project Structure

```
src/rhythms/
├── config/
│   ├── agents.yaml    # Agent definitions
│   └── tasks.yaml     # Task configurations
├── crew.py           # Core crew logic
└── main.py          # Entry point
```

## How It Works

The Rhythms Crew orchestrates multiple AI agents, each with specific roles and capabilities. These agents work together on tasks defined in your configuration files, combining their specialized skills to achieve complex objectives efficiently.

## Resources

- [Documentation](https://docs.crewai.com)
- [GitHub Repository](https://github.com/joaomdmoura/crewai)
- [Discord Community](https://discord.com/invite/X4JWnZnxPb)
- [Documentation Chat](https://chatg.pt/DWjSBZn)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

[Add your license information here]
