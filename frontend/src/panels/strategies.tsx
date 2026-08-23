import { useState, useMemo } from "react";
import type { Strategy } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SectionHeader } from "@/components/metric-card";
import { EmptyState } from "@/components/feedback";
import { useStrategiesQuery } from "@/hooks/use-strategies-query";
import { Search, RefreshCw, ChevronRight } from "lucide-react";

export function StrategiesPanel() {
  // REV-019-RV6: shared hook — polling no longer depends on mount order.
  const { data, isLoading, error, refetch, isFetching } = useStrategiesQuery();

  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    if (!data) return [];
    if (!search.trim()) return data;
    const q = search.toLowerCase();
    return data.filter(
      (s) =>
        s.strategy_id.toLowerCase().includes(q) ||
        s.title.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q) ||
        s.symbols.some((sym) => sym.toLowerCase().includes(q)),
    );
  }, [data, search]);

  const selected = useMemo(() => {
    if (!selectedId || !data) return null;
    return data.find((s) => s.strategy_id === selectedId) ?? null;
  }, [data, selectedId]);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-sm text-muted-foreground">加载中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <Card className="max-w-md">
          <CardContent className="pt-6">
            <p className="text-destructive">加载失败: {error.message}</p>
            <Button onClick={() => refetch()} className="mt-4">
              重试
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="@container space-y-4">
      {/* Header — RC-1 (P2-4): 流式标题 */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-panel-title font-bold">策略目录</h2>
          <p className="text-sm text-muted-foreground">
            共 {data?.length ?? 0} 个策略
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
          <RefreshCw className={`mr-2 h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="搜索策略名称、ID 或交易对..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="pl-9"
        />
        {search && (
          // RC-3: 清除按钮 h-9 w-9（≥36px，改进自 24px）
          <Button
            variant="ghost"
            size="sm"
            className="absolute right-1 top-1/2 h-8 w-8 -translate-y-1/2"
            onClick={() => setSearch("")}
            aria-label="清空搜索"
          >
            <span className="text-xs font-medium">×</span>
          </Button>
        )}
      </div>

      {/* Content */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Strategy List */}
        <div className="space-y-2">
          {filtered.length === 0 && (
            // RC-4 (P2-12): 空状态 = 确认 + 价值 + 行动
            <EmptyState
              title="没有匹配的策略"
              description="尝试更换关键词，或清空搜索条件查看所有策略。"
              action={search && (
                <Button variant="outline" size="sm" onClick={() => setSearch("")}>
                  清空搜索
                </Button>
              )}
            />
          )}
          {filtered.map((strategy) => (
            <StrategyListItem
              key={strategy.strategy_id}
              strategy={strategy}
              isSelected={selectedId === strategy.strategy_id}
              onSelect={() => setSelectedId(strategy.strategy_id)}
            />
          ))}
        </div>

        {/* Detail Panel */}
        <div className="lg:sticky lg:top-4 lg:self-start">
          {selected ? (
            <StrategyDetail strategy={selected} onClose={() => setSelectedId(null)} />
          ) : (
            <Card>
              <CardContent className="py-12 text-center text-sm text-muted-foreground">
                选择一个策略查看详情
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function StrategyListItem({
  strategy,
  isSelected,
  onSelect,
}: {
  strategy: Strategy;
  isSelected: boolean;
  onSelect: () => void;
}) {
  return (
    <Card
      className={`cursor-pointer transition-colors hover:bg-accent/5 ${
        isSelected ? "border-primary" : ""
      }`}
      onClick={onSelect}
    >
      <CardContent className="flex items-center justify-between p-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-sm font-semibold">{strategy.title}</h3>
            <Badge variant="outline" className="shrink-0 text-xs">
              {strategy.strategy_id}
            </Badge>
          </div>
          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
            {strategy.description}
          </p>
          <div className="mt-2 flex flex-wrap gap-1">
            {strategy.symbols.map((sym) => (
              <Badge key={sym} variant="secondary" className="text-xs">
                {sym}
              </Badge>
            ))}
            {strategy.timeframe && (
              <Badge variant="outline" className="text-xs">
                {strategy.timeframe}
              </Badge>
            )}
          </div>
        </div>
        <ChevronRight className="ml-2 h-4 w-4 shrink-0 text-muted-foreground" />
      </CardContent>
    </Card>
  );
}

function StrategyDetail({ strategy, onClose }: { strategy: Strategy; onClose: () => void }) {
  const params = Object.entries(strategy.params);
  const paramSpace = Object.entries(strategy.param_space);

  return (
    <Card className="border-primary/30">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div>
            <CardTitle className="text-sm">{strategy.title}</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">{strategy.strategy_id}</p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <span className="text-xs font-medium">×</span>
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Description */}
        <div>
          <SectionHeader title="描述" />
          <p className="text-sm text-muted-foreground">{strategy.description}</p>
        </div>

        {/* Symbols & Timeframe */}
        <div>
          <SectionHeader title="交易配置" />
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">交易对:</span>
              <div className="flex flex-wrap gap-1">
                {strategy.symbols.map((sym) => (
                  <Badge key={sym} variant="secondary" className="text-xs">
                    {sym}
                  </Badge>
                ))}
              </div>
            </div>
            {strategy.timeframe && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">时间周期:</span>
                <Badge variant="outline" className="text-xs">
                  {strategy.timeframe}
                </Badge>
              </div>
            )}
          </div>
        </div>

        {/* Parameters */}
        {params.length > 0 && (
          <div>
            <SectionHeader title="当前参数" />
            <div className="space-y-1 rounded-lg bg-muted/30 p-3">
              {params.map(([key, value]) => (
                <div key={key} className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">{key}</span>
                  <span className="font-mono">{JSON.stringify(value)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Parameter Space */}
        {paramSpace.length > 0 && (
          <div>
            <SectionHeader title="参数空间" subtitle="可用于优化的参数范围" />
            <div className="space-y-1 rounded-lg bg-muted/30 p-3">
              {paramSpace.map(([key, value]) => (
                <div key={key} className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">{key}</span>
                  <span className="font-mono">{JSON.stringify(value)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Config Path */}
        <div>
          <SectionHeader title="配置文件" />
          <p className="truncate rounded bg-muted/30 px-2 py-1 font-mono text-xs text-muted-foreground">
            {strategy.config_path}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
