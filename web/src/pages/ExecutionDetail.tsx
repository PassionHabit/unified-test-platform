import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Card, Descriptions, Tag, Timeline, Table, Button, Tabs, Space, Statistic, message,
} from "antd";
import { api, STATUS_COLOR, OUTCOME_COLOR } from "../api";

export default function ExecutionDetail() {
  const { id } = useParams();
  const [exec, setExec] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [logs, setLogs] = useState<string>("");
  const [logStream, setLogStream] = useState<"stdout" | "stderr">("stdout");
  const [artifacts, setArtifacts] = useState<any[]>([]);
  const [result, setResult] = useState<any>(null);

  const load = () => {
    api(`/api/v1/executions/${id}`).then(setExec).catch(() => {});
    api(`/api/v1/executions/${id}/events`).then(setEvents).catch(() => {});
    api(`/api/v1/executions/${id}/artifacts`).then(setArtifacts).catch(() => {});
    api(`/api/v1/executions/${id}/result`).then(setResult).catch(() => setResult(null));
    fetch(`/api/v1/executions/${id}/logs?stream=${logStream}`)
      .then((r) => (r.ok ? r.text() : ""))
      .then(setLogs)
      .catch(() => {});
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [id, logStream]);

  if (!exec) return <Card loading title="执行详情" />;
  const running = !["COMPLETED", "FAILED", "CANCELLED"].includes(exec.status);

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Card title={`执行 #${exec.id}`}>
        <Descriptions column={3} size="small">
          <Descriptions.Item label="状态">
            <Tag color={STATUS_COLOR[exec.status]}>{exec.status}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="结论">
            <Tag color={OUTCOME_COLOR[exec.outcome]}>{exec.outcome}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="失败原因">{exec.failure_reason}</Descriptions.Item>
          <Descriptions.Item label="源码版本">{exec.source_revision}</Descriptions.Item>
          <Descriptions.Item label="超时(s)">{exec.timeout_seconds}</Descriptions.Item>
          <Descriptions.Item label="优先级">{exec.priority}</Descriptions.Item>
          <Descriptions.Item label="创建">{exec.created_at?.replace("T", " ").slice(0, 19)}</Descriptions.Item>
          <Descriptions.Item label="开始">{exec.started_at?.replace("T", " ").slice(0, 19) || "-"}</Descriptions.Item>
          <Descriptions.Item label="结束">{exec.ended_at?.replace("T", " ").slice(0, 19) || "-"}</Descriptions.Item>
        </Descriptions>
        {running && (
          <Button
            danger
            style={{ marginTop: 12 }}
            onClick={async () => {
              await api(`/api/v1/executions/${id}/cancel`, { method: "POST" });
              message.success("已请求取消");
              load();
            }}
          >
            取消执行
          </Button>
        )}
      </Card>

      {result && (
        <Card title="结果摘要" size="small">
          <Space size="large">
            <Statistic title="总数" value={result.total} />
            <Statistic title="通过" value={result.passed} valueStyle={{ color: "#52c41a" }} />
            <Statistic title="失败" value={result.failed} valueStyle={{ color: "#ff4d4f" }} />
            <Statistic title="跳过" value={result.skipped} />
          </Space>
          {result.failures?.length > 0 && (
            <Table
              style={{ marginTop: 12 }}
              size="small"
              rowKey={(r: any) => r.name + r.classname}
              pagination={false}
              dataSource={result.failures}
              columns={[
                { title: "用例", dataIndex: "name" },
                { title: "类", dataIndex: "classname" },
              ]}
            />
          )}
        </Card>
      )}

      <Card title="时间线 / 日志 / 产物" size="small">
        <Tabs
          items={[
            {
              key: "events",
              label: "事件",
              children: (
                <Timeline
                  items={events.map((e) => ({
                    color: e.event_type === "execution.finalized" ? "green" : "blue",
                    children: (
                      <>
                        <b>{e.event_type}</b>
                        <div style={{ color: "#888", fontSize: 12 }}>
                          {e.created_at?.replace("T", " ").slice(0, 19)}
                        </div>
                        {Object.keys(e.payload || {}).length > 0 && (
                          <pre style={{ fontSize: 12, margin: 0 }}>{JSON.stringify(e.payload)}</pre>
                        )}
                      </>
                    ),
                  }))}
                />
              ),
            },
            {
              key: "logs",
              label: "日志",
              children: (
                <>
                  <Space style={{ marginBottom: 8 }}>
                    <Button size="small" type={logStream === "stdout" ? "primary" : "default"} onClick={() => setLogStream("stdout")}>stdout</Button>
                    <Button size="small" type={logStream === "stderr" ? "primary" : "default"} onClick={() => setLogStream("stderr")}>stderr</Button>
                  </Space>
                  <pre
                    style={{
                      background: "#111", color: "#0f0", padding: 12, borderRadius: 6,
                      maxHeight: 420, overflow: "auto", fontSize: 12,
                    }}
                  >
                    {logs || "（暂无已上传日志分片）"}
                  </pre>
                </>
              ),
            },
            {
              key: "artifacts",
              label: "产物",
              children: (
                <Table
                  size="small"
                  rowKey="path"
                  pagination={false}
                  dataSource={artifacts}
                  columns={[
                    { title: "路径", dataIndex: "path" },
                    { title: "大小", dataIndex: "size", render: (s) => `${s ?? 0} B` },
                    {
                      title: "", width: 120,
                      render: (_: any, a: any) => (
                        <a href={`/api/v1/executions/${id}/artifacts?download=true#${a.path}`}
                           onClick={async (e) => {
                             e.preventDefault();
                             const list = await api(`/api/v1/executions/${id}/artifacts?download=true`);
                             const item = list.find((x: any) => x.path === a.path);
                             if (item?.download_url) window.open(item.download_url, "_blank");
                           }}>
                          下载
                        </a>
                      ),
                    },
                  ]}
                />
              ),
            },
          ]}
        />
      </Card>
    </Space>
  );
}
