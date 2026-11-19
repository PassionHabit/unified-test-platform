import { Layout, Menu } from "antd";
import {
  ExperimentOutlined,
  CloudUploadOutlined,
  FolderOutlined,
  ClusterOutlined,
} from "@ant-design/icons";
import { Routes, Route, NavLink, useLocation } from "react-router-dom";
import Executions from "./pages/Executions";
import ExecutionDetail from "./pages/ExecutionDetail";
import Submit from "./pages/Submit";
import Projects from "./pages/Projects";
import Nodes from "./pages/Nodes";

const { Sider, Header, Content } = Layout;

export default function App() {
  const loc = useLocation();
  const selected = loc.pathname.startsWith("/executions")
    ? "/executions"
    : loc.pathname.startsWith("/projects")
    ? "/projects"
    : loc.pathname.startsWith("/nodes")
    ? "/nodes"
    : "/submit";

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider theme="dark" width={200}>
        <div style={{ color: "#fff", padding: 20, fontSize: 16, fontWeight: 600 }}>
          统一测试平台
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selected]}
          items={[
            { key: "/submit", icon: <CloudUploadOutlined />, label: <NavLink to="/submit">提交执行</NavLink> },
            { key: "/executions", icon: <ExperimentOutlined />, label: <NavLink to="/executions">执行列表</NavLink> },
            { key: "/projects", icon: <FolderOutlined />, label: <NavLink to="/projects">项目管理</NavLink> },
            { key: "/nodes", icon: <ClusterOutlined />, label: <NavLink to="/nodes">节点监控</NavLink> },
          ]}
        />
      </Sider>
      <Layout>
        <Header style={{ background: "#fff", padding: "0 24px", fontSize: 14, color: "#888" }}>
          Unified Test Platform Console
        </Header>
        <Content style={{ margin: 16 }}>
          <Routes>
            <Route path="/" element={<Submit />} />
            <Route path="/submit" element={<Submit />} />
            <Route path="/executions" element={<Executions />} />
            <Route path="/executions/:id" element={<ExecutionDetail />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/nodes" element={<Nodes />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  );
}
