import { useEffect, useState } from "react";
import { Card, Table, Tag, Progress } from "antd";
import { api } from "../api";

const STATE_COLOR: Record<string, string> = {
  ACTIVE: "success",
  DRAINING: "warning",
  OFFLINE: "default",
};

export default function Nodes() {
  const [nodes, setNodes] = useState<any[]>([]);

  useEffect(() => {
    const load = () => api("/api/v1/nodes").then(setNodes).catch(() => {});
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <Card title="节点监控">
      <Table
        rowKey="id"
        size="middle"
        dataSource={nodes}
        pagination={false}
        columns={[
          { title: "ID", dataIndex: "id", width: 60 },
          { title: "Agent", dataIndex: "agent_id" },
          { title: "类型", dataIndex: "type", width: 90, render: (t) => <Tag>{t}</Tag> },
          { title: "标签", dataIndex: "labels", render: (l) => (l || []).map((x: string) => <Tag key={x}>{x}</Tag>) },
          {
            title: "CPU", width: 160,
            render: (_: any, n: any) =>
              n.cpu_total > 0 ? (
                <Progress
                  size="small"
                  percent={Math.round((n.cpu_reserved / n.cpu_total) * 100)}
                  format={() => `${n.cpu_reserved}/${n.cpu_total}`}
                />
              ) : (
                "-"
              ),
          },
          {
            title: "内存(MB)", width: 160,
            render: (_: any, n: any) =>
              n.memory_total > 0 ? (
                <Progress
                  size="small"
                  percent={Math.round((n.memory_reserved / n.memory_total) * 100)}
                  format={() => `${n.memory_reserved}/${n.memory_total}`}
                />
              ) : (
                "-"
              ),
          },
          {
            title: "维护状态", dataIndex: "maintenance_state", width: 110,
            render: (s) => <Tag color={STATE_COLOR[s]}>{s}</Tag>,
          },
          {
            title: "心跳", dataIndex: "heartbeat_at", width: 190,
            render: (t) => (t ? t.replace("T", " ").slice(0, 19) : "-"),
          },
        ]}
      />
    </Card>
  );
}
