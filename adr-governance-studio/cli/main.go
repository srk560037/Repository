package main

import (
	"fmt"
	"os"
	"path/filepath"
	"time"
)

const adrTemplate = `---
id: %s
title: %s
status: Proposed
date: %s
authors: ["%s"]
tags: ["architecture"]
---

## Context
Describe the context and problem statement here.

## Decision
State the architecture decision clearly.

## Consequences
- Positive outcome
- Potential trade-off
`

func main() {
	if len(os.Args) < 2 {
		fmt.Println("Usage: adr <command> [args]")
		fmt.Println("Commands: init, new <title>, list")
		os.Exit(1)
	}

	cmd := os.Args[1]
	switch cmd {
	case "init":
		err := os.MkdirAll(".adr/decisions", 0755)
		if err != nil {
			fmt.Printf("Error initializing ADR repository: %v\n", err)
			return
		}
		fmt.Println("✓ Initialized ADR repository in .adr/decisions/")

	case "new":
		if len(os.Args) < 3 {
			fmt.Println("Usage: adr new <title>")
			return
		}
		title := os.Args[2]
		timestamp := time.Now().Format("2006-01-02")
		filename := fmt.Sprintf("ADR-%d-%s.md", time.Now().Unix(), filepath.Base(title))
		filePath := filepath.Join(".adr/decisions", filename)

		content := fmt.Sprintf(adrTemplate, filename, title, timestamp, "Architect")
		err := os.WriteFile(filePath, []byte(content), 0644)
		if err != nil {
			fmt.Printf("Error creating ADR file: %v\n", err)
			return
		}
		fmt.Printf("✓ Created new ADR: %s\n", filePath)

	case "list":
		files, err := os.ReadDir(".adr/decisions")
		if err != nil {
			fmt.Println("No ADR directory found. Run 'adr init' first.")
			return
		}
		fmt.Println("Architecture Decision Records:")
		for _, file := range files {
			fmt.Printf(" - %s\n", file.Name())
		}

	default:
		fmt.Printf("Unknown command: %s\n", cmd)
	}
}
