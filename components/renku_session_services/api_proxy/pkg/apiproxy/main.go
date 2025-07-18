package apiproxy

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"time"

	"github.com/SwissDataScienceCenter/renku-data-services/components/renku_session_services/api_proxy/pkg/config"
	"github.com/SwissDataScienceCenter/renku-data-services/components/renku_session_services/api_proxy/pkg/tokenstore"
	"github.com/labstack/echo/v4"
	"github.com/labstack/echo/v4/middleware"
)

func Run() {
	config, err := config.LoadAndValidateConfig()
	if err != nil {
		slog.Error("loading the configuration failed", "error", err)
		os.Exit(1)
	}
	slog.Info("loaded configuration", "config", config)

	e, err := createServer(config)
	if err != nil {
		slog.Error("creating the API proxy failed", "error", err)
		os.Exit(1)
	}

	// Start server
	address := fmt.Sprintf("%s:%d", config.Host, config.Port)
	slog.Info("starting the server on address " + address)
	go func() {
		err := e.Start(address)
		if err != nil && err != http.ErrServerClosed {
			slog.Error("shutting down the server gracefuly failed", "error", err)
			os.Exit(1)
		}
	}()

	// Wait for interrupt signal to gracefully shutdown the server with a timeout of 10 seconds.
	// Use a buffered channel to avoid missing signals as recommended for signal.Notify
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, os.Interrupt)
	<-quit
	slog.Info("received signal to shut down the server")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := e.Shutdown(ctx); err != nil {
		slog.Error("shutting down the server gracefully failed", "error", err)
		os.Exit(1)
	}
}

// createServer creates the API Proxy server
func createServer(config config.Config) (e *echo.Echo, err error) {
	e = echo.New()
	e.Pre(middleware.RequestID(), middleware.RemoveTrailingSlash())
	e.Use(middleware.Recover())

	// Hide the echo banner
	e.HideBanner = true
	e.HidePort = true

	// Dummy health check
	e.GET("/health", func(c echo.Context) error {
		return c.NoContent(http.StatusOK)
	})

	store := tokenstore.New(&config)
	ap, err := NewApiProxy(WithConfig(config), WithTokenStore(store))
	if err != nil {
		return nil, err
	}
	ap.RegisterHandlers(e)

	return e, nil
}
