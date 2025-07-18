package log

import (
	"log/slog"
	"os"
)

var logLevel *slog.LevelVar = new(slog.LevelVar)
var jsonLogger *slog.Logger = slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: logLevel}))

func SetupLogging() {
	slog.SetDefault(jsonLogger)
}
